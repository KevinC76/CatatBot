from __future__ import annotations

import asyncio
import logging
from datetime import date

from notion_client import AsyncClient
from notion_client.errors import APIResponseError

from config import config

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [2, 5, 10]


def _get_client() -> AsyncClient:
    return AsyncClient(auth=config.NOTION_API_KEY)


async def save_expense(
    nominal: int,
    kategori: str,
    deskripsi: str,
    tanggal: str,
    tipe: str = "Pengeluaran",
    mata_uang: str = "IDR",
    nominal_asli: float | None = None,
    kurs: float | None = None,
) -> bool:
    props: dict = {
        "Deskripsi": {"title": [{"text": {"content": deskripsi}}]},
        "Tanggal":   {"date": {"start": tanggal}},
        "Nominal":   {"number": nominal},
        "Kategori":  {"select": {"name": kategori}},
        "Tipe":      {"select": {"name": tipe}},
        "Mata Uang": {"select": {"name": mata_uang}},
    }
    if nominal_asli is not None:
        props["Nominal Asli"] = {"number": nominal_asli}
    if kurs is not None:
        props["Kurs"] = {"number": kurs}

    payload = {"parent": {"database_id": config.NOTION_DATABASE_ID}, "properties": props}

    for attempt, delay in enumerate([0] + _RETRY_DELAYS, start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            async with _get_client() as notion:
                await notion.pages.create(**payload)
            return True
        except APIResponseError as e:
            logger.warning("Notion save attempt %d failed: %s", attempt, e)
        except Exception as e:
            logger.warning("Notion save attempt %d error: %s", attempt, e)

    return False


async def get_expenses(start_date: str, end_date: str) -> list[dict]:
    results, cursor = [], None

    async with _get_client() as notion:
        while True:
            kwargs: dict = {
                "database_id": config.NOTION_DATABASE_ID,
                "filter": {
                    "and": [
                        {"property": "Tanggal", "date": {"on_or_after": start_date}},
                        {"property": "Tanggal", "date": {"on_or_before": end_date}},
                    ]
                },
                "sorts": [{"property": "Tanggal", "direction": "ascending"}],
                "page_size": 100,
            }
            if cursor:
                kwargs["start_cursor"] = cursor

            try:
                response = await notion.databases.query(**kwargs)
            except Exception as e:
                logger.error("Notion query failed: %s", e)
                break

            for page in response.get("results", []):
                props = page.get("properties", {})
                try:
                    nominal      = props["Nominal"]["number"] or 0
                    kategori     = (props["Kategori"]["select"] or {}).get("name", "Lainnya")
                    tanggal      = (props["Tanggal"]["date"] or {}).get("start", "")
                    title_parts  = props["Deskripsi"]["title"]
                    deskripsi    = title_parts[0]["text"]["content"] if title_parts else ""
                    tipe         = (props.get("Tipe", {}).get("select") or {}).get("name", "Pengeluaran")
                    mata_uang    = (props.get("Mata Uang", {}).get("select") or {}).get("name", "IDR")
                    nominal_asli = props.get("Nominal Asli", {}).get("number")
                    kurs         = props.get("Kurs", {}).get("number")

                    results.append({
                        "nominal":      nominal,
                        "nominal_asli": nominal_asli,
                        "mata_uang":    mata_uang,
                        "kurs":         kurs,
                        "kategori":     kategori,
                        "tanggal":      tanggal,
                        "deskripsi":    deskripsi,
                        "tipe":         tipe,
                    })
                except (KeyError, IndexError, TypeError):
                    continue

            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")

    return results


def aggregate_by_category(expenses: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for e in expenses:
        totals[e["kategori"]] = totals.get(e["kategori"], 0) + e["nominal"]
    return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))


def split_by_tipe(expenses: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (pengeluaran_list, pemasukan_list)."""
    pengeluaran = [e for e in expenses if e.get("tipe", "Pengeluaran") == "Pengeluaran"]
    pemasukan   = [e for e in expenses if e.get("tipe") == "Pemasukan"]
    return pengeluaran, pemasukan
