"""Wiring: builds the services once per process."""
from __future__ import annotations

from dataclasses import dataclass

from mundus_world.config.settings import Settings, load_settings
from mundus_world.repo.db import Database
from mundus_world.service.claims import Claims
from mundus_world.service.search import Search
from mundus_world.service.world import World


@dataclass
class Container:
    settings: Settings
    db: Database
    claims: Claims
    world: World
    search: Search


def build(settings: Settings | None = None) -> Container:
    s = settings or load_settings()
    db = Database(s.db_path)
    claims = Claims(db, s.predicates_path)
    return Container(settings=s, db=db, claims=claims, world=World(s, db, claims), search=Search(s, db))
