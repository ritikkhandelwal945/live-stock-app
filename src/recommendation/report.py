import json
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from src.client.models import Recommendation

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def _action_color(action: str) -> str:
    colors = {
        "STRONG BUY": "bold green",
        "BUY": "green",
        "HOLD": "yellow",
        "SELL": "red",
        "STRONG SELL": "bold red",
    }
    return colors.get(action, "white")


def print_recommendations(recommendations: list[Recommendation], console: Console | None = None) -> None:
    console = console or Console()

    # Summary table
    table = Table(title="Portfolio Analysis & Recommendations", show_lines=True)
    table.add_column("Stock", style="bold cyan", min_width=12)
    table.add_column("Price", justify="right", min_width=10)
    table.add_column("Action", justify="center", min_width=12)
    table.add_column("Score", justify="right", min_width=8)
    table.add_column("Confidence", justify="right", min_width=10)
    table.add_column("Tech", justify="right", min_width=8)
    table.add_column("Fund", justify="right", min_width=8)
    table.add_column("News", justify="right", min_width=8)

    # Sort: strong buy first, strong sell last
    order = {"STRONG BUY": 0, "BUY": 1, "HOLD": 2, "SELL": 3, "STRONG SELL": 4}
    sorted_recs = sorted(recommendations, key=lambda r: order.get(r.action, 2))

    for rec in sorted_recs:
        action_text = Text(rec.action, style=_action_color(rec.action))
        table.add_row(
            rec.tradingsymbol,
            f"{rec.current_price:,.2f}",
            action_text,
            f"{rec.score:+.3f}",
            f"{rec.confidence:.0f}%",
            f"{rec.technical_score:+.3f}",
            f"{rec.fundamental_score:+.3f}",
            f"{rec.news_score:+.3f}",
        )

    console.print()
    console.print(table)

    # Detailed panels for each stock
    for rec in sorted_recs:
        reasons_text = "\n".join(f"  - {r}" for r in rec.reasons) if rec.reasons else "  No specific signals"
        panel_text = (
            f"Price: {rec.current_price:,.2f}\n"
            f"Action: {rec.action} (score: {rec.score:+.3f}, confidence: {rec.confidence:.0f}%)\n"
            f"Technical: {rec.technical_score:+.3f} | Fundamental: {rec.fundamental_score:+.3f} | News: {rec.news_score:+.3f}\n\n"
            f"Reasons:\n{reasons_text}"
        )
        console.print(Panel(panel_text, title=f"[bold]{rec.tradingsymbol}[/bold]", border_style=_action_color(rec.action)))

    console.print()


def save_recommendations(recommendations: list[Recommendation]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    filepath = DATA_DIR / f"analysis_{date.today().isoformat()}.json"
    data = [rec.model_dump() for rec in recommendations]
    filepath.write_text(json.dumps(data, indent=2, default=str))
    return filepath


def format_single_stock(rec: Recommendation) -> str:
    lines = [
        f"Stock: {rec.tradingsymbol}",
        f"Price: {rec.current_price:,.2f}",
        f"Action: {rec.action}",
        f"Score: {rec.score:+.3f} (Confidence: {rec.confidence:.0f}%)",
        f"Technical: {rec.technical_score:+.3f}",
        f"Fundamental: {rec.fundamental_score:+.3f}",
        f"News: {rec.news_score:+.3f}",
        "",
        "Reasons:",
    ]
    for r in rec.reasons:
        lines.append(f"  - {r}")
    return "\n".join(lines)
