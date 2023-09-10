import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher, types, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from magic_filter import F
from api.bookings.ApiBookings import ApiBookings
from api.bookings.Booking import Booking
from api.meetings.ApiMeetings import ApiMeetings
from api.meetings.Meeting import Meeting
from api.members.ApiMembers import ApiMember
from api.members.Member import Member
from clb_queries import ClbShowList, ClbShowDetail, ClbAdd, ClbDelete, ClbPrefix
from api.places.Place import Place
from api.tickets.Ticket import Ticket
from msg_texts.MessagesText import MessagesText
from msg_texts.ButtonsText import ButtonsText
from settings import TOKEN, HOST, ADMIN_CHANEL_ID
from api.settings import datetime_format_str, datetime_format_str_api


bot = Bot(token=TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

msg_text = MessagesText()
btn_text = ButtonsText()

api_members = ApiMember(HOST)
api_meetings = ApiMeetings(HOST)
api_bookings = ApiBookings(HOST)


@router.message(Command("start"))
async def start_menu(message: types.Message):
    from_user = message.from_user
    member = await api_members.get_member_by_tg_id(tg_id=from_user.id)
    if not member:
        new_member = Member(
            tg_id=from_user.id,
            login=from_user.mention,
            name=from_user.first_name,
            surname=from_user.last_name,
        )
        await api_members.add_member(new_member=new_member)

    bnt_builder = InlineKeyboardBuilder()
    postfixes: dict = {
        ClbPrefix.dates: "Даты",
    }

    for postfix, text in postfixes.items():
        bnt_builder.button(
            text=text,
            callback_data=ClbShowList(postfix=postfix).pack()
        )
    await message.answer(
        text=msg_text.get_hello(),
        reply_markup=bnt_builder.as_markup(),
    )


@router.callback_query(ClbShowList.filter(F.postfix == ClbPrefix.dates))
async def callback_dates(callback_query: types.CallbackQuery):
    await asyncio.gather(before_(callback_query.id))

    meetings: list[Meeting] = await api_meetings.get_future_meetings()
    if not meetings:
        await bot.send_message(
            callback_query.from_user.id,
            text="Мы готовим ближайшие встречи и скоро вы сможете записаться на них",
        )
        return

    def get_date_time(m: Meeting) -> datetime:
        return m.get_date_time()

    meetings.sort(key=get_date_time)
    btn_builder: InlineKeyboardBuilder = InlineKeyboardBuilder()
    for meeting in meetings:
        meeting_date: str = meeting.get_date_time().strftime(datetime_format_str)
        meeting_name: str = f"{meeting_date} - {meeting.get_place().get_name()}"
        btn_builder.button(
            text=meeting_name,
            callback_data=ClbShowDetail(postfix=ClbPrefix.meeting, pk=meeting.get_pk()),
        )

    btn_builder.adjust(1)

    await bot.send_message(
        callback_query.from_user.id,
        text=msg_text.get_club_dates(),
        reply_markup=btn_builder.as_markup(),
    )


@router.callback_query(ClbShowDetail.filter(F.postfix == ClbPrefix.meeting))
async def callback_meetings(callback_query: types.CallbackQuery, callback_data: ClbShowDetail):
    await asyncio.gather(before_(callback_query.id))

    meeting: Meeting = await api_meetings.get_meeting_by_pk(pk=callback_data.pk)
    if not meeting:
        await bot.send_message(
            callback_query.from_user.id,
            text="Похоже, что то сломалось, "
                 "я не смог найти встречу, на которую вы хотите записаться( Напишите моим разработчикам",
            reply_to_message_id=callback_query.message.message_id,
        )
        return
    elif not meeting.get_tickets():
        await bot.send_message(
            callback_query.from_user.id,
            text="Бронирований на эту встречу пока что нет, они появятся чуть позже",
            reply_to_message_id=callback_query.message.message_id,
        )
        return

    member: Member = await api_members.get_member_by_tg_id(tg_id=callback_query.from_user.id)
    if not member:
        await bot.send_message(
            callback_query.from_user.id,
            text="Похоже, что то сломалось, "
                 "я не смог вас узнать, напишите, пожалуйста, моим разработчикам",
            reply_to_message_id=callback_query.message.message_id,
        )
        return

    btn_builder = InlineKeyboardBuilder()
    free_tickets: list[Ticket] = meeting.get_free_tickets()
    member_ticket = meeting.get_ticket_by_tg_id(tg_id=member.get_tg_id())
    if member_ticket:
        if not member_ticket:
            await bot.send_message(
                callback_query.from_user.id,
                text="Похоже, что то сломалось, "
                     "я не смог найти ваш билет, напишите, пожалуйста, моим разработчикам",
                reply_to_message_id=callback_query.message.message_id,
            )
        btn_builder.button(
            text="Отменить бронирование",
            callback_data=ClbDelete(postfix=ClbPrefix.booking, pk=meeting.get_pk())
        )
        tickets_info: str = msg_text.get_booking_already()
    elif free_tickets:
        btn_builder.button(
            text=btn_text.get_booking(),
            callback_data=ClbAdd(postfix=ClbPrefix.booking, pk=meeting.get_pk())
        )
        tickets_info: str = msg_text.get_cnt_free_tickets(len(free_tickets))
    else:
        tickets_info: str = msg_text.get_no_tickets()

    meeting_date: str = meeting.get_date_time().strftime(datetime_format_str)
    place: Place = meeting.get_place()
    place_text = f"[{place.get_name()}]({place.get_link()})"
    text = "\n".join((
        msg_text.get_date_and_time(meeting_date),
        msg_text.get_place(place_text),
        "\n" + tickets_info
    ))

    btn_builder.adjust(1)

    await bot.send_message(
        callback_query.from_user.id,
        text=text,
        reply_markup=btn_builder.as_markup(),
        reply_to_message_id=callback_query.message.message_id,
    )


@router.callback_query(ClbAdd.filter(F.postfix == ClbPrefix.booking))
async def add_booking(callback_query: types.CallbackQuery, callback_data: ClbAdd):
    await asyncio.gather(before_(callback_query.id))

    # todo добавить оплату

    member: Member = await api_members.get_member_by_tg_id(tg_id=callback_query.from_user.id)
    if not member:
        await bot.send_message(
            callback_query.from_user.id,
            text="Похоже, что то сломалось, "
                 "я не смог вас узнать, напишите, пожалуйста, моим разработчикам",
            reply_to_message_id=callback_query.message.message_id,
        )
        return

    # todo добавить условие что тьюторы могут бронировать места без денег
    # todo система оповещений пользователей что скоро занятие
    meeting = await api_meetings.get_meeting_by_pk(pk=callback_data.pk)
    if meeting.check_booking_by_td_id(tg_id=member.get_tg_id()):
        await bot.send_message(
            callback_query.from_user.id,
            text=msg_text.get_booking_already(),
            reply_to_message_id=callback_query.message.message_id,
        )
        return

    free_tickets = meeting.get_free_tickets()
    if not free_tickets:
        await bot.send_message(
            callback_query.from_user.id,
            text=msg_text.get_no_tickets(),
            reply_to_message_id=callback_query.message.message_id,
        )
        return

    try:
        await api_bookings.add_booking(
            new_booking=Booking(
                date_time=datetime.now().strftime(datetime_format_str_api),
                is_paid=False,
            ),
            ticket_id=free_tickets[0].get_pk(),
            member_id=member.get_pk(),
        )
    except Exception as e:
        text = msg_text.get_smt_went_wrong()
    else:
        text = msg_text.get_booking_success()

    await bot.send_message(
        callback_query.from_user.id,
        text=text,
        reply_to_message_id=callback_query.message.message_id,
    )


@router.callback_query(ClbDelete.filter(F.postfix == ClbPrefix.booking))
async def delete_booking(callback_query: types.CallbackQuery, callback_data: ClbDelete):
    await before_(callback_query_id=callback_query.id)

    meeting = await api_meetings.get_meeting_by_pk(pk=callback_data.pk)
    member_ticket = meeting.get_ticket_by_tg_id(tg_id=callback_query.from_user.id)
    if not member_ticket:
        text = "Похоже, что то вы уже отменили бронирование на эту встречу"
    else:
        result = await api_bookings.delete_booking(pk=member_ticket.get_booking().get_pk())
        if result:
            text = "Бронирование отменено, посмотри встречи на другую дату"
            notif_text = f"какой то хмырь с логином {member_ticket.get_booking_member().get_name()} отменил бронирование на встречу {meeting.get_name()}"
            await bot.send_message(
                ADMIN_CHANEL_ID,
                text=notif_text,
            )
        else:
            text = "Похоже, что то вы уже отменили бронирование на эту встречу"

    await bot.send_message(
        callback_query.from_user.id,
        text=text,
        reply_to_message_id=callback_query.message.message_id
    )


async def before_(callback_query_id: str) -> None:
    await bot.answer_callback_query(callback_query_id)


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
