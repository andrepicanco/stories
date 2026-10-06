"""Extrai organização, projeto, time e nível de backlog da URL de um board do Azure DevOps."""
from dataclasses import asdict, dataclass
from urllib.parse import unquote, urlparse


class InvalidBoardUrl(ValueError):
    pass


@dataclass(frozen=True)
class BoardContext:
    org_url: str
    organization: str
    project: str
    team: str
    backlog_level: str

    def to_dict(self) -> dict:
        return asdict(self)


def parse_board_url(url: str) -> BoardContext:
    """Espera https://dev.azure.com/{org}/{projeto}/_boards/board/t/{time}/{nível}."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != "dev.azure.com":
        raise InvalidBoardUrl("A URL deve começar com https://dev.azure.com/.")

    parts = [unquote(p) for p in parsed.path.split("/") if p]
    # [org, projeto, "_boards", "board", "t", time, nível?]
    if len(parts) < 6 or parts[2] != "_boards" or parts[3] != "board" or parts[4] != "t":
        raise InvalidBoardUrl(
            "URL de board inválida. Use o link do board, no formato "
            "https://dev.azure.com/{org}/{projeto}/_boards/board/t/{time}/{nível}."
        )

    organization, project, team = parts[0], parts[1], parts[5]
    level = parts[6] if len(parts) > 6 else "Stories"
    return BoardContext(
        org_url=f"https://dev.azure.com/{organization}",
        organization=organization,
        project=project,
        team=team,
        backlog_level=level,
    )
