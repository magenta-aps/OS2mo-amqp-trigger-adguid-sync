from typing import Any
from uuid import UUID
from datetime import date

from .dataloaders import Dataloaders
from more_itertools import one
from more_itertools import only

from ramodels.mo.details import ITUser
from raclients.modelclient.mo import ModelClient


async def ensure_adguid_itsystem(
    user: UUID,
    dataloaders: Dataloaders,
    model_client: ModelClient,
) -> None:
    """Ensure that an ADGUID IT-system exists in MO for the given user.

    Args:
        user: UUID of the user to ensure existence for.

    Returns:
        None
    """
    itsystem_uuid = await dataloaders.itsystems_loader.load("Active Directory")
    user = await dataloaders.users_loader.load(user)
    has_ituser = any(map(
        lambda ituser: ituser.itsystem_uuid == itsystem_uuid,
        user.itusers
    ))
    if has_ituser:
        print("ITUser already exists")
        return

    adguid = await dataloaders.adguid_loader.load(user.cpr_no)
    print(adguid)

    ituser = ITUser.from_simplified_fields(
        user_key=str(adguid),
        itsystem_uuid=itsystem_uuid,
        person_uuid=user.uuid,
        from_date=date.today().isoformat(),
    )
    print(ituser)
    # TODO: Upload dataloader?
    response = await model_client.upload([ituser])
    print(response)
    return True
