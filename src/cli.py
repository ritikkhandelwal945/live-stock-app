import click
from rich.console import Console
from rich.table import Table

from dotenv import load_dotenv

load_dotenv()

console = Console()


@click.group()
def cli():
    """Stock Analysis & Recommendation App - powered by Zerodha Kite Connect"""
    pass


@cli.command()
@click.option("--manual", is_flag=True, help="Manual token entry (for headless environments)")
def auth(manual: bool):
    """Authenticate with Zerodha Kite Connect."""
    from src.auth.kite_auth import login
    try:
        login(manual=manual)
        console.print("[green]Authentication successful![/green]")
    except Exception as e:
        console.print(f"[red]Authentication failed: {e}[/red]")
        raise SystemExit(1)


@cli.command()
def holdings():
    """Display current portfolio holdings."""
    from src.client.kite_client import KiteClient

    try:
        client = KiteClient()
        h = client.get_holdings()

        if not h:
            console.print("[yellow]No holdings found.[/yellow]")
            return

        table = Table(title="Portfolio Holdings", show_lines=True)
        table.add_column("Symbol", style="bold cyan")
        table.add_column("Qty", justify="right")
        table.add_column("Avg Price", justify="right")
        table.add_column("Last Price", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Day Change %", justify="right")

        total_pnl = 0.0
        for stock in h:
            pnl_style = "green" if stock.pnl >= 0 else "red"
            day_style = "green" if stock.day_change_percentage >= 0 else "red"
            table.add_row(
                stock.tradingsymbol,
                str(stock.quantity),
                f"{stock.average_price:,.2f}",
                f"{stock.last_price:,.2f}",
                f"[{pnl_style}]{stock.pnl:+,.2f}[/{pnl_style}]",
                f"[{day_style}]{stock.day_change_percentage:+.2f}%[/{day_style}]",
            )
            total_pnl += stock.pnl

        console.print(table)
        pnl_style = "green" if total_pnl >= 0 else "red"
        console.print(f"\nTotal P&L: [{pnl_style}]{total_pnl:+,.2f}[/{pnl_style}]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command()
def positions():
    """Display current open positions."""
    from src.client.kite_client import KiteClient

    try:
        client = KiteClient()
        pos = client.get_positions()

        if not pos:
            console.print("[yellow]No open positions.[/yellow]")
            return

        table = Table(title="Open Positions", show_lines=True)
        table.add_column("Symbol", style="bold cyan")
        table.add_column("Qty", justify="right")
        table.add_column("Buy Price", justify="right")
        table.add_column("Sell Price", justify="right")
        table.add_column("P&L", justify="right")
        table.add_column("Product", justify="center")

        for p in pos:
            pnl_style = "green" if p.pnl >= 0 else "red"
            table.add_row(
                p.tradingsymbol,
                str(p.quantity),
                f"{p.buy_price:,.2f}",
                f"{p.sell_price:,.2f}",
                f"[{pnl_style}]{p.pnl:+,.2f}[/{pnl_style}]",
                p.product,
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command()
@click.argument("symbol")
@click.option("--days", default=365, help="Historical data lookback days")
def analyze(symbol: str, days: int):
    """Analyze a single stock with technical indicators."""
    from src.client.kite_client import KiteClient
    from src.analysis.technical import analyze as tech_analyze
    from src.analysis.fundamental import FundamentalSignals
    from src.analysis.news import NewsSignals
    from src.recommendation.engine import score_stock
    from src.recommendation.report import format_single_stock

    try:
        client = KiteClient()
        symbol = symbol.upper()

        console.print(f"[cyan]Fetching data for {symbol}...[/cyan]")
        df = client.get_historical_data(symbol, days=days)
        quotes = client.get_quote([symbol])
        quote = quotes.get(symbol)
        current_price = quote.last_price if quote else (df["close"].iloc[-1] if not df.empty else 0)

        console.print(f"[cyan]Running technical analysis ({len(df)} candles)...[/cyan]")
        tech = tech_analyze(df)

        # Technical signals detail
        for ind in tech.indicators:
            color = "green" if ind.signal == "bullish" else ("red" if ind.signal == "bearish" else "yellow")
            console.print(f"  [{color}]{ind.name}: {ind.detail}[/{color}]")

        console.print(f"\n[bold]Technical Score: {tech.overall_score:+.3f} ({tech.summary})[/bold]")

        # Generate recommendation (technical-only for CLI single stock)
        fund = FundamentalSignals()
        news = NewsSignals()
        rec = score_stock(symbol, current_price, tech, fund, news)
        console.print(f"\n{format_single_stock(rec)}")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command()
@click.option("--days", default=365, help="Historical data lookback days")
def recommend(days: int):
    """Analyze all holdings and generate recommendations."""
    from src.client.kite_client import KiteClient
    from src.analysis.technical import analyze as tech_analyze
    from src.analysis.fundamental import FundamentalSignals
    from src.analysis.news import NewsSignals
    from src.recommendation.engine import score_stock
    from src.recommendation.report import print_recommendations, save_recommendations

    try:
        client = KiteClient()
        h = client.get_holdings()

        if not h:
            console.print("[yellow]No holdings found.[/yellow]")
            return

        console.print(f"[cyan]Analyzing {len(h)} stocks...[/cyan]\n")
        recommendations = []

        for i, stock in enumerate(h, 1):
            symbol = stock.tradingsymbol
            console.print(f"[dim][{i}/{len(h)}] Analyzing {symbol}...[/dim]")

            try:
                df = client.get_historical_data(symbol, days=days)
                tech = tech_analyze(df)
                current_price = stock.last_price or (df["close"].iloc[-1] if not df.empty else 0)

                fund = FundamentalSignals()
                news = NewsSignals()
                rec = score_stock(symbol, current_price, tech, fund, news)
                recommendations.append(rec)
            except Exception as e:
                console.print(f"  [red]Failed to analyze {symbol}: {e}[/red]")
                continue

        if recommendations:
            print_recommendations(recommendations, console)
            filepath = save_recommendations(recommendations)
            console.print(f"[dim]Results saved to {filepath}[/dim]")
        else:
            console.print("[yellow]No stocks could be analyzed.[/yellow]")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
