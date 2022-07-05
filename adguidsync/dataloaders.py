from contextlib import asynccontextmanager
from typing import AsyncIterator
from dataclasses import dataclass
from functools import partial
from operator import itemgetter
from uuid import UUID

from gql import gql
from gql.client import AsyncClientSession
from strawberry.dataloader import DataLoader
from more_itertools import unzip
from more_itertools import one
from pydantic import BaseModel
from pydantic import parse_obj_as

from fastramqpi.main import FastRAMQPI


@dataclass
class Dataloaders:
    users_loader: DataLoader
    itsystems_loader: DataLoader
    adguid_loader: DataLoader


class ITUser(BaseModel):
    itsystem_uuid: UUID
    uuid: UUID
    user_key: str


class User(BaseModel):
    itusers: list[ITUser]
    cpr_no: str
    user_key: str
    uuid: UUID


async def load_users(keys: list[UUID], graphql_session: AsyncClientSession) -> list[User]:
    query = gql("""
    query User(
      $uuids: [UUID!]
    ) {
      employees(uuids: $uuids) {
        objects {
          itusers {
            itsystem_uuid
            uuid
            user_key
          }
          cpr_no
          user_key
          uuid
        }
      }
    }
    """)
    result = await graphql_session.execute(query, variable_values={"uuids": list(set(map(str, keys)))})
    users = parse_obj_as(list[User], list(map(one, map(itemgetter("objects"), result["employees"]))))
    user_map = {user.uuid: user for user in users}
    return [user_map.get(key) for key in keys]


async def load_itsystems(keys: list[str], graphql_session: AsyncClientSession) -> list[UUID]:
    query = gql("query ITSystemsQuery { itsystems { uuid, user_key } }")
    result = await graphql_session.execute(query)
    user_keys, uuids = unzip(map(itemgetter("user_key", "uuid"), result["itsystems"]))
    uuids = map(UUID, uuids)
    itsystems_map = dict(zip(user_keys, uuids))
    return [itsystems_map.get(key) for key in keys]


from ra_utils.generate_uuid import generate_uuid

async def load_adguid(keys: list[str]) -> list[UUID]:
    # TODO: Implement AD lookup
    return [
        generate_uuid("adguidsync", key)
        for key in keys
    ]


@asynccontextmanager
async def seed_dataloaders(fastramqpi: FastRAMQPI) -> AsyncIterator[None]:
    # TODO: Dataloaders need to be cacheless or reset to clear cache
    # TODO: Dataloaders need to use call_later instead of call_soon
    graphql_loader_functions = {
        "users_loader": load_users,
        "itsystems_loader": load_itsystems,
    }

    graphql_session = fastramqpi._context["graphql_session"]
    graphql_dataloaders = {
        key: DataLoader(
            load_fn=partial(value, graphql_session=graphql_session),
            cache=False
        )
        for key, value in graphql_loader_functions.items()
    }

    adguid_loader = DataLoader(load_fn=load_adguid, cache=False)

    dataloaders = Dataloaders(**graphql_dataloaders, adguid_loader=adguid_loader)
    fastramqpi.add_context(dataloaders=dataloaders)

    yield
