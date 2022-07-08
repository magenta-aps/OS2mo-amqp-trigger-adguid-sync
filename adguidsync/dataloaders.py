# SPDX-FileCopyrightText: 2019-2020 Magenta ApS
#
# SPDX-License-Identifier: MPL-2.0
"""Dataloaders to bulk requests."""
import json
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
from pydantic import Json
from ldap3 import Connection

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


def ad_response_to_cpr_uuid_map(ad_response: Json, cpr_attribute: str) -> dict[str, UUID]:
    """Convert our AD Response to a CPR-->UUID dictionary.

    Example input:
        ```Python
        {
            "entries": [
                {
                    "attributes": {
                        "extensionAttribute3": "0101709999",
                        "objectGUID": "{ccc5f858-5044-4093-a4c2-b2ecb595201e}"
                    },
                    "dn": "CN=John Efternavn,OU=...,DC=Kommune,DC=net"
                },
                {
                    "attributes": {
                        "extensionAttribute3": "3112700000",
                        "objectGUID": "{d34513c5-2649-4045-b0a3-038da5d3765b}"
                    },
                    "dn": "CN=Hanne Efternavn,OU=...,DC=Kommune,DC=net"
                }
            ]
        }
        ```

    Args:
        ad_response: The JSON-paresd response from the AD.

    Returns:
        mapping from CPR-numbers to AD GUIDs.
    """
    users = list(map(itemgetter("attributes"), ad_response["entries"]))
    cpr_nos = map(itemgetter(cpr_attribute), users)
    guids = map(
        lambda guid_str: UUID(guid_str.strip("{}")),
        map(itemgetter("objectGUID"), users)
    )
    return dict(zip(cpr_nos, guids))


async def load_adguid(
    keys: list[str],
    ad_connection: Connection,
    cpr_attribute: str,
    search_base: str,
) -> list[UUID]:
    # Construct our search filter by OR'ing all CPR numbers together
    cpr_conditions = "".join(map(lambda cpr: f"({cpr_attribute}={cpr})", keys))
    search_filter = "(&(objectclass=user)(|" + cpr_conditions + "))"

    ad_connection.search(
        search_base=search_base,
        search_filter=search_filter,
        # Search in the entire subtree of search_base
        search_scope = "SUBTREE",
        # Fetch only CPR and objectGUID attributes
        attributes = [cpr_attribute, 'objectGUID'],
    )
    json_str = ad_connection.response_to_json()
    ad_response = json.loads(json_str)

    cpr_to_uuid_map = ad_response_to_cpr_uuid_map(ad_response, cpr_attribute)
    return [cpr_to_uuid_map.get(key) for key in keys]


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

    settings = fastramqpi._context["user_context"]["settings"]
    ad_connection = fastramqpi._context["user_context"]["ad_connection"]
    adguid_loader = DataLoader(
        load_fn=partial(
            load_adguid,
            ad_connection=ad_connection,
            cpr_attribute=settings.ad_cpr_attribute,
            search_base=settings.ad_search_base,
        ),
        cache=False
    )

    dataloaders = Dataloaders(**graphql_dataloaders, adguid_loader=adguid_loader)
    fastramqpi.add_context(dataloaders=dataloaders)

    yield
