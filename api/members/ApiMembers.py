

from api.base.ApiBase import ApiBase, T_HOST
from .Member import Member
from ..bookings.Booking import Booking
from ..subscribes.Subscribe import Subscribe


class ApiMember(ApiBase):
    def __init__(self, base_url: T_HOST):
        super().__init__(base_url)

    async def get_members(self) -> list[Member]:
        members = await self._api_get_members()
        return [Member(**member) for member in members]

    async def get_member_by_pk(self, pk: int) -> Member | None:
        member = await self._api_get_members(id=pk)
        return Member(**member[0]) if member else None

    async def get_member_by_tg_id(self, tg_id: int) -> Member | None:
        member = await self._api_get_members(tg_id=tg_id)
        return Member(**member[0]) if member else None

    async def get_member_bookings(self, member: Member) -> list[Booking]:
        bookings = await self._api_get_bookings(member_id=member.get_pk())
        return [Booking(**booking) for booking in bookings]

    async def get_subscribes(self, member: Member) -> list[Subscribe]:
        subscribes = await self._api_get_subscribes(member_id=member.get_pk())
        return [Subscribe(**subscribe) for subscribe in subscribes]

    async def get_active_subscribe(self, member: Member) -> Subscribe | None:
        subscribe = await self._api_get_subscribes(
            member_id=member.get_pk(),
            is_active=True
        )
        return Subscribe(**subscribe[0]) if subscribe else None

    async def get_bookings_by_subscribe(self, member: Member) -> Subscribe | None:
        bookings = await self._api_get_subscribes(
            subscribe_id=member.get_pk(),
            is_active=True
        )
        return Subscribe(**subscribe[0]) if subscribe else None

    async def add_member(self, new_member: Member) -> Member:
        result: dict = await self._api_add_member(
            tg_id=new_member.get_tg_id(),
            login=new_member.get_login(),
            name=new_member.get_name(),
            surname=new_member.get_surname(),
        )
        if result:
            return Member(**result)
        else:
            raise
