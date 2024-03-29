from .Ticket import Ticket
from api.base.ApiBase import ApiBase, T_HOST


class ApiTickets(ApiBase):
    def __init__(self, base_url: T_HOST):
        super().__init__(base_url)

    async def get_tickets(self) -> list[Ticket]:
        tickets = await self._api_get_tickets()
        return [Ticket(**ticket) for ticket in tickets]
