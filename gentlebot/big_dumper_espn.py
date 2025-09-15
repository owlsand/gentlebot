from __future__ import annotations
"""Fetch Big Dumper data from ESPN's public APIs."""

import re
from datetime import datetime
from typing import Any

import aiohttp
from dateutil import tz

# Seattle team/athlete constants
SEA_TEAM_ABBR = "SEA"
SEA_TEAM_NAME = "Mariners"
SEA_TEAM_SLUG = "sea"
RALEIGH_ID = 41459

UTC = tz.gettz("UTC")


class ESPN:
    """Thin async wrapper around the unofficial ESPN MLB endpoints."""

    BASE_COMMON = "https://site.api.espn.com/apis/common/v3/sports/baseball/mlb"
    BASE_V2 = "https://site.api.espn.com/apis/v2/sports/baseball/mlb"

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.sess = session

    async def get(self, url: str, **params: Any) -> Any:
        async with self.sess.get(url, params=params, timeout=20) as r:
            r.raise_for_status()
            return await r.json()

    async def athlete(self, athlete_id: int) -> Any:
        return await self.get(f"{self.BASE_COMMON}/athletes/{athlete_id}")

    async def athlete_splits(self, athlete_id: int, season: int) -> Any:
        return await self.get(f"{self.BASE_COMMON}/athletes/{athlete_id}/splits", season=season)

    async def athlete_gamelog(self, athlete_id: int, season: int) -> Any:
        return await self.get(f"{self.BASE_COMMON}/athletes/{athlete_id}/gamelog", season=season)

    async def team_with_schedule(self, team_slug: str) -> Any:
        return await self.get(f"{self.BASE_V2}/teams/{team_slug}", enable="schedule")

    async def standings(self, season: int) -> Any:
        return await self.get(f"{self.BASE_V2}/standings", season=season)

    async def playbyplay(self, event_id: str) -> Any:
        return await self.get(f"{self.BASE_V2}/playbyplay", event=event_id)

    async def summary(self, event_id: str) -> Any:
        return await self.get(f"{self.BASE_V2}/summary", event=event_id)


def _find_stat(stats_obj: dict | None, key_names: list[str]) -> str | None:
    if not stats_obj:
        return None
    try:
        for split in stats_obj.get("splits", []):
            for cat in split.get("categories", []):
                for st in cat.get("stats", []):
                    name = (st.get("name") or st.get("displayName") or "").lower()
                    if any(k.lower() == name for k in key_names):
                        return st.get("value") or st.get("displayValue")
    except Exception:
        pass
    return None


def _fmt_pct(val: str | None) -> str | None:
    if not val:
        return None
    try:
        v = float(val)
        return f"{v:.3f}".lstrip("0")
    except Exception:
        return val


def _parse_split_line(split_group: dict, label: str) -> dict:
    for grp in split_group.get("splits", []):
        if str(grp.get("displayName", "")).lower().startswith(label.lower()):
            cats: dict[str, str] = {}
            for cat in grp.get("categories", []):
                for st in cat.get("stats", []):
                    cats[st.get("name", "")] = st.get("value") or st.get("displayValue")
            avg = _fmt_pct(cats.get("avg") or cats.get("battingAverage"))
            obp = _fmt_pct(cats.get("obp") or cats.get("onBasePct"))
            slg = _fmt_pct(cats.get("slg") or cats.get("sluggingPct"))
            hr = cats.get("homeRuns") or cats.get("HR")
            return {"slash": f"{avg}/{obp}/{slg}" if all([avg, obp, slg]) else None, "hr": hr}
    return {"slash": None, "hr": None}


def _feet_ev_from_text(text: str) -> tuple[str | None, str | None]:
    if not text:
        return None, None
    ft = re.search(r"(\d{3,4})\s?ft", text)
    ev = re.search(r"(\d{2,3}\.\d)\s?mph", text)
    return (ft.group(1) if ft else None, ev.group(1) if ev else None)


def _local_day(dt_iso: str, tz_name: str = "America/Los_Angeles") -> str:
    try:
        from_zone = tz.gettz("UTC")
        to_zone = tz.gettz(tz_name)
        dt = datetime.fromisoformat(dt_iso.replace("Z", "+00:00")).astimezone(to_zone)
        return dt.strftime("%b %d")
    except Exception:
        return dt_iso[:10]


async def gather_big_dumper_data(athlete_id: int = RALEIGH_ID, season: int | None = None) -> dict:
    season = season or datetime.now(tz=UTC).year
    async with aiohttp.ClientSession(headers={"User-Agent": "gentlebot/1.0"}) as s:
        api = ESPN(s)
        athlete_json = await api.athlete(athlete_id)
        stats = athlete_json.get("statistics") or {}
        hr = _find_stat(stats, ["homeRuns", "HR"])
        rbi = _find_stat(stats, ["runsBattedIn", "RBI"])
        ops = _fmt_pct(_find_stat(stats, ["ops"]))
        slg = _fmt_pct(_find_stat(stats, ["sluggingPct", "SLG"]))
        avg = _fmt_pct(_find_stat(stats, ["battingAverage", "AVG"]))

        splits = await api.athlete_splits(athlete_id, season)
        l7 = _parse_split_line(splits, "last 7")
        l15 = _parse_split_line(splits, "last 15")
        post = _parse_split_line(splits, "post all-star") or _parse_split_line(splits, "since all-star")

        gamelog = await api.athlete_gamelog(athlete_id, season)
        games = gamelog.get("events") or gamelog.get("items") or []
        normalized = []
        for g in games:
            event_id = str(g.get("id") or g.get("eventId") or g.get("event", {}).get("id", ""))
            abbr_opp = (
                g.get("opponent", {}).get("abbreviation")
                or g.get("opponent", {}).get("shortDisplayName", "")
            )
            homeAway = g.get("homeAway") or (g.get("isHome") and "home" or "away")
            stats_map: dict[str, Any] = {}
            for st in g.get("stats") or []:
                stats_map[st.get("name") or st.get("displayName")] = st.get("value") or st.get("displayValue")
            normalized.append(
                {
                    "eventId": event_id,
                    "date": g.get("date") or g.get("startDate") or "",
                    "opponent": abbr_opp,
                    "homeAway": homeAway,
                    "HR": int(str(stats_map.get("homeRuns") or stats_map.get("HR") or 0) or 0),
                }
            )
        team_games_played = len([g for g in normalized if g.get("date")])
        hr_int = int(hr or 0)
        pace = round((hr_int / max(team_games_played, 1)) * 162)

        latest_hr_events = [
            g
            for g in sorted(normalized, key=lambda x: x["date"], reverse=True)
            if g.get("HR", 0) > 0
        ][:3]
        last_hr_detail: dict[str, Any] | None = None
        last3_lines: list[tuple[str, str]] = []
        for idx, g in enumerate(latest_hr_events):
            pbp = await api.playbyplay(g["eventId"]) if g["eventId"] else {}
            play_hit = None
            for drive in pbp.get("drives", []) + pbp.get("items", []):
                plays = drive.get("plays", []) if "plays" in drive else [drive]
                for pl in plays:
                    t = (pl.get("type", {}) or {}).get("text", "").lower()
                    inv = pl.get("athletesInvolved") or []
                    if "home run" in t or "homered" in (pl.get("text", "").lower()):
                        if any(str(a.get("id")) == str(athlete_id) for a in inv):
                            play_hit = pl
                            break
                if play_hit:
                    break
            if play_hit:
                text = play_hit.get("text") or play_hit.get("headline") or ""
                ft, ev = _feet_ev_from_text(text)
                media = play_hit.get("media") or {}
                video_url = None
                if isinstance(media, dict):
                    for l in media.get("links", []):
                        if l.get("href"):
                            video_url = l["href"]
                            break
                if not video_url:
                    video_url = f"https://www.espn.com/mlb/playbyplay/_/gameId/{g['eventId']}"
                if idx == 0:
                    last_hr_detail = {
                        "num": hr,
                        "date": _local_day(g["date"]),
                        "opp": g["opponent"],
                        "ft": ft,
                        "ev": ev,
                        "url": video_url,
                    }
                line = f"#{int(hr_int - (idx))}  {g['date'][:10]}  {'@' if g['homeAway']=='away' else 'vs'}{g['opponent']}"
                if ft or ev:
                    line += f"  {ft + ' ft' if ft else ''}{'  ' if ft and ev else ''}{ev + ' EV' if ev else ''}"
                line += "  Video"
                last3_lines.append((line, video_url))
            else:
                line = f"#{int(hr_int - (idx))}  {g['date'][:10]}  {'@' if g['homeAway']=='away' else 'vs'}{g['opponent']}"
                last3_lines.append((line, f"https://www.espn.com/mlb/game/_/gameId/{g['eventId']}"))

        std = await api.standings(season)
        al_west = None
        def iter_teams(node):
            for ch in node.get("children", []):
                yield ch
                yield from iter_teams(ch)
        for g in iter_teams(std):
            if g.get("name", "").lower() in ("al west", "american league west", "west"):
                if any("American League" in (p.get("name", "")) for p in g.get("parents", [])) or "al" in (
                    g.get("abbreviation", "").lower()
                ):
                    al_west = g
        if not al_west:
            candidates = [
                g
                for g in iter_teams(std)
                if g.get("standings", {}).get("entries")
                and len(g["standings"]["entries"]) == 5
                and "west" in g.get("name", "").lower()
            ]
            al_west = candidates[0] if candidates else None

        rank = gb = streak = last10 = "—"
        record_overall = division_leader = "—"
        if al_west:
            entries = al_west["standings"]["entries"]
            norm = []
            for e in entries:
                t = e.get("team", {})
                recs = {i.get("type"): i for i in e.get("records", [])}
                overall = recs.get("overall") or recs.get("total")
                gb_val = recs.get("division").get("gamesBehind") if recs.get("division") else None
                streak_val = (
                    next((i.get("summary") for i in e.get("streaks", []) if i.get("type") == "current"), None)
                    or overall.get("streak")
                )
                last10_val = next(
                    (i.get("summary") for i in e.get("records", []) if i.get("name", "").lower() == "last 10"),
                    None,
                )
                if not last10_val:
                    last10_val = next(
                        (i.get("summary") for i in e.get("stats", []) if i.get("name", "").lower() == "last10"),
                        None,
                    )
                norm.append(
                    {
                        "abbr": t.get("abbreviation"),
                        "name": t.get("displayName"),
                        "rank": e.get("rank"),
                        "overall": overall.get("summary") if overall else "",
                        "gb": str(gb_val) if gb_val is not None else "—",
                        "streak": streak_val or "—",
                        "last10": last10_val or "—",
                    }
                )
            leader = norm[0]["abbr"] if norm else "—"
            for row in norm:
                if row["abbr"] == SEA_TEAM_ABBR:
                    rank, gb, streak, last10 = row["rank"], row["gb"], row["streak"], row["last10"]
                    record_overall = row["overall"]
                    division_leader = leader

        data = {
            "season_strip": {
                "HR": hr,
                "RBI": rbi,
                "OPS": ops,
                "SLG": slg,
                "AVG": avg,
            },
            "recent": {"l7": l7, "l15": l15, "post": post},
            "pace": pace,
            "latest_hr": last_hr_detail,
            "last3_hrs": last3_lines,
            "standings": {
                "rank": rank,
                "gb": gb,
                "streak": streak,
                "last10": last10,
                "overall": record_overall,
                "leader": division_leader,
            },
        }
        return data


def build_compact_message(d: dict) -> str:
    s = d["season_strip"]
    st = d["standings"]
    l7 = d["recent"]["l7"]["slash"]
    l7_hr = d["recent"]["l7"]["hr"]
    line: list[str] = []
    line.append(f"Big Dumper Tracker — {datetime.now().strftime('%b %d')}")
    strip = f"Season   HR {s['HR']} • RBI {s['RBI']} • OPS {s['OPS']}"
    line.append(strip)
    if l7:
        recent = f"Recent   L7: {l7} ({l7_hr or 0} HR) • Streak: {st['streak']}"
        line.append(recent)
    line.append(f"Pace     {d['pace']} HR over 162")
    if d["latest_hr"]:
        L = d["latest_hr"]
        meta = " • ".join(
            x
            for x in [
                f"{L['date']}",
                f"@{L['opp']}",
                f"{L['ft']} ft" if L['ft'] else None,
                f"{L['ev']} EV" if L['ev'] else None,
            ]
            if x
        )
        line.append(f"Latest   #{L['num']} — {meta} — Video: {L['url']}")
    line.append(
        f"AL West  {st['rank']} • {st['gb']} GB of {st['leader']} • L10: {st['last10']}"
    )
    return "```\n" + "\n".join(line) + "\n```"


def build_rich_embed_payload(d: dict) -> dict:
    s, st = d["season_strip"], d["standings"]
    desc = (
        f"HR **{s['HR']}** • RBI **{s['RBI']}** • OPS **{s['OPS']}** • SLG {s['SLG']} • AVG {s['AVG']}"
    )
    l7 = d["recent"]["l7"]["slash"]
    l7hr = d["recent"]["l7"]["hr"]
    l15 = d["recent"]["l15"]["slash"]
    l15hr = d["recent"]["l15"]["hr"]
    post = d["recent"]["post"]["slash"]
    posthr = d["recent"]["post"]["hr"]
    form_lines = []
    if l7:
        form_lines.append(f"**L7**  {l7} ({l7hr or 0} HR)")
    if l15:
        form_lines.append(f"**L15** {l15} ({l15hr or 0} HR)")
    if post:
        form_lines.append(f"**Post** {post} (since ASG)")
    form_val = "\n".join(form_lines) if form_lines else "—"
    if d["last3_hrs"]:
        last3 = "\n".join([f"{t}  [Video]({u})" for (t, u) in d["last3_hrs"]])
    else:
        last3 = "—"
    fields = [
        {"name": "Form", "value": form_val, "inline": True},
        {"name": "Last 3 HRs", "value": last3, "inline": True},
        {
            "name": "AL West",
            "value": f"{st['rank']} • {st['gb']} GB of {st['leader']} • L10: {st['last10']}",
            "inline": False,
        },
        {"name": "Pace", "value": f"{d['pace']} HR over 162", "inline": True},
    ]
    payload = {
        "title": f"Big Dumper — Season Snapshot ({datetime.now().strftime('%b %d')})",
        "description": desc,
        "fields": fields,
        "thumbnail": {"url": "https://a.espncdn.com/i/teamlogos/mlb/500/sea.png"},
        "color": 10181046,
    }
    return payload


async def demo(style: str = "compact") -> Any:
    data = await gather_big_dumper_data(RALEIGH_ID)
    if style == "compact":
        return build_compact_message(data)
    return build_rich_embed_payload(data)
