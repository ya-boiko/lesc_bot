import asyncio
import json
from datetime import datetime
from typing import Any

from aiogram import Bot, Dispatcher, types, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import User
from aiogram.utils.keyboard import InlineKeyboardBuilder
from magic_filter import F

from TgButtons import TgButtons
from TgButtonsAdmin import TgButtonsAdmin
from TgButtonsUser import TgButtonsUser
from api.bookings.ApiBookings import ApiBookings
from api.bookings.Booking import Booking
from api.meetings.ApiMeetings import ApiMeetings
from api.meetings.Meeting import Meeting
from api.members.ApiMembers import ApiMember
from api.members.Member import Member
from clb_queries import ClbShowList, ClbShowDetail, ClbAdd, ClbDelete, Postfix, ClbConfirm
from api.tickets.Ticket import Ticket
from texts.Admins import Admins
from texts.Errors import Errors
from texts.Messages import Messages
from settings import TOKEN, HOST, ADMIN_CHANEL_ID, REDIS_HOST, REDIS_PORT
from api.settings import datetime_format_str_api
from utils.RedisHandler import RedisHandler
from utils.Service import Service

bot = Bot(token=TOKEN, parse_mode=ParseMode.MARKDOWN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

text_msg = Messages()
text_errors = Errors()
text_admins = Admins()

api_members = ApiMember(HOST)
api_meetings = ApiMeetings(HOST)
api_bookings = ApiBookings(HOST)

db_redis = RedisHandler(host=REDIS_HOST, port=REDIS_PORT)


@router.message(Command("start"))
async def start(message: types.Message):
    from_user: User = message.from_user
    member: Member = await api_members.get_member_by_tg_id(tg_id=from_user.id)
    if not member:
        await Service.add_member(tg_user=from_user)

    bnt_builder: InlineKeyboardBuilder = TgButtonsUser.get_start_menu()

    await message.answer(
        text=text_msg.hello(),
        reply_markup=bnt_builder.as_markup(),
    )


@router.message()
async def delete_message(message: types.Message):
    await bot.delete_message(
        chat_id=message.chat.id,
        message_id=message.message_id
    )


@router.callback_query(ClbShowList.filter(F.postfix == Postfix.start))
async def show_start_menu(callback: types.CallbackQuery):
    btn_builder: InlineKeyboardBuilder = TgButtonsUser.get_start_menu()

    await replace_last_msg(
        callback=callback,
        text=text_msg.hello(),
        btn_builder=btn_builder
    )
    await after_(callback=callback)


@router.callback_query(ClbShowList.filter(F.postfix == Postfix.dates))
async def show_meetings_list(callback: types.CallbackQuery):
    meetings: list[Meeting] = await api_meetings.get_future_meetings()
    if not meetings:
        return await send_answer(
            callback=callback,
            text=text_msg.no_meetings()
        )

    btn_builder: InlineKeyboardBuilder = TgButtonsUser.get_meetings(meetings=meetings)
    btn_builder: InlineKeyboardBuilder = TgButtonsUser.add_back(
        builder=btn_builder,
        callback=ClbShowList(postfix=Postfix.start)
    )
    btn_builder.adjust(1)

    await replace_last_msg(
        callback=callback,
        text=text_msg.meetings_dates(),
        btn_builder=btn_builder
    )
    await after_(callback=callback)


@router.callback_query(ClbShowDetail.filter(F.postfix == Postfix.meeting))
async def show_meeting_detail(callback: types.CallbackQuery, callback_data: ClbShowDetail):
    meeting: Meeting = await api_meetings.get_meeting_by_pk(pk=callback_data.pk)

    if not meeting:
        text: str = text_errors.cant_find_meeting()
        return await send_answer(callback=callback, text=text)
    elif not meeting.get_tickets() or not meeting.get_can_be_booked():
        text: str = text_msg.booking_unavailable()
        return await send_answer(callback=callback, text=text)

    member: Member = await api_members.get_member_by_tg_id(tg_id=callback.from_user.id)
    if not member:
        text: str = text_errors.strange_member()
        return await send_answer(callback=callback, text=text)

    meeting_text: str = Service.get_meeting_text(member=member, meeting=meeting)

    btn_builder: InlineKeyboardBuilder = TgButtonsUser.get_meeting(member=member, meeting=meeting)
    btn_builder: InlineKeyboardBuilder = TgButtonsUser.add_back(
        builder=btn_builder,
        callback=ClbShowList(postfix=Postfix.dates)
    )
    btn_builder.adjust(1)

    await replace_last_msg(
        callback=callback,
        text=meeting_text,
        btn_builder=btn_builder
    )
    await after_(callback=callback)


@router.callback_query(ClbAdd.filter(F.postfix == Postfix.booking))
async def add_booking(callback: types.CallbackQuery, callback_data: ClbAdd):
    member: Member = await api_members.get_member_by_tg_id(tg_id=callback.from_user.id)
    if not member:
        text: str = text_errors.strange_member()
        return await send_answer(callback=callback, text=text)

    # todo система оповещений пользователей что скоро занятие
    meeting: Meeting = await api_meetings.get_meeting_by_pk(pk=callback_data.pk)
    ticket: Ticket = meeting.get_ticket_by_tg_id(member.get_tg_id())
    if ticket:
        booking: Booking = ticket.get_booking()
        redis_key: str = db_redis.get_key_confirm(name=Postfix.booking, pk=booking.get_pk())
        redis_booking: str = db_redis.get(redis_key)

        if booking.is_paid():
            text: str = text_msg.booking_success_pay_success()
        elif redis_booking:
            text: str = text_msg.booking_success_pay_confirm()
        else:
            text: str = text_msg.booking_already()

        return await send_answer(callback=callback, text=text)

    free_tickets: list[Ticket] = meeting.get_free_tickets()
    if not free_tickets:
        return await send_answer(callback=callback, text=text_msg.no_free_tickets())

    btn_builder: InlineKeyboardBuilder = TgButtons.get_empty_builder()
    try:
        await api_bookings.add_booking(
            new_booking=Booking(
                date_time=datetime.now().strftime(datetime_format_str_api),
                is_paid=False,
                user_confirm_paid=False,
            ),
            ticket_id=free_tickets[0].get_pk(),
            member_id=member.get_pk(),
        )
    except Exception as e:
        text: str = Service.get_meeting_text(
            member,
            meeting,
            False,
            f"\n{text_errors.smt_went_wrong()}",
            f"\n{text_errors.try_one_more_time()}",
        )
        btn_builder = TgButtonsUser.add_booking(
            builder=btn_builder,
            pk=meeting.get_pk(),
        )
    else:
        text: str = Service.get_meeting_text(
            member,
            meeting,
            False,
            f"\n{text_msg.booking_success()}",
            f"\n{text_msg.payment_info()}",
        )
        btn_builder = TgButtonsUser.add_payment_confirm(
            builder=btn_builder,
            pk=meeting.get_pk(),
        )
        btn_builder = TgButtonsUser.add_booking_cancel(
            builder=btn_builder,
            pk=meeting.get_pk(),
        )

    btn_builder: InlineKeyboardBuilder = TgButtonsUser.add_back(
        builder=btn_builder,
        callback=ClbShowList(postfix=Postfix.dates)
    )
    btn_builder.adjust(1)

    await replace_last_msg(callback, text, btn_builder)
    await after_(callback)


@router.callback_query(ClbConfirm.filter(F.postfix == Postfix.confirm_booking))
async def confirm_booking(callback: types.CallbackQuery, callback_data: ClbConfirm):
    meeting: Meeting = await api_meetings.get_meeting_by_pk(pk=callback_data.pk)
    ticket: Ticket = meeting.get_ticket_by_tg_id(tg_id=callback.from_user.id)
    if not ticket:
        return await send_answer(
            callback=callback,
            text=text_msg.no_member_ticket()
        )

    booking: Booking = ticket.get_booking()
    member: Member = ticket.get_booking_member()

    redis_key: str = db_redis.get_key_confirm(name=Postfix.booking, pk=booking.get_pk())
    redis_info = db_redis.get(redis_key)

    if redis_info:
        return await send_answer(
            callback=callback,
            text=text_msg.booking_success_pay_confirm()
        )
    elif booking.is_paid():
        return await send_answer(
            callback=callback,
            text=text_msg.booking_success_pay_success()
        )
    else:
        booking.set_user_confirm_paid(value=True)
        try:
            await api_bookings.update_booking(booking=booking)
        except Exception as e:
            # todo добавить логирование
            # todo вместо разработчкам писать ссылку на чат с леском (где все тьюторы)
            return await send_answer(
                callback=callback,
                text=text_errors.booking_error()
            )

        text: str = Service.get_meeting_text(
            member,
            meeting,
            False,
            f"\n{text_msg.booking_success()}",
            f"\n{text_msg.booking_success_pay_confirm()}",
        )
        btn_builder = TgButtonsUser.get_meeting(member=member, meeting=meeting)
        await replace_last_msg(callback=callback, btn_builder=btn_builder, text=text)

        db_redis.set(
            key=redis_key,
            value=json.dumps({
                "meeting_pk": meeting.get_pk(),
                "member_tg_id": member.get_tg_id(),
                "user_chat_id": callback.from_user.id,
                "msg_to_user_id": callback.message.message_id,
            })
        )

        btn_builder_adm = TgButtons.get_empty_builder()
        btn_builder_adm = TgButtonsAdmin.add_confirm_payment(
            builder=btn_builder_adm,
            pk=booking.get_pk(),
        )
        btn_builder_adm = TgButtonsAdmin.add_booking_cancel(
            builder=btn_builder_adm,
            pk=booking.get_pk(),
        )

        btn_builder_adm.adjust(1)

        if member.get_login():
            user_info: str = f"[{member.get_full_name()}]({member.get_link()})"
        else:
            user_info: str = member.get_full_name()

        notif_text: str = text_admins.confirm_pay(
            user_info=user_info,
            meeting_info=meeting.get_name(),
        )
        await bot.send_message(
            chat_id=ADMIN_CHANEL_ID,
            text=notif_text,
            reply_markup=btn_builder_adm.as_markup(),
        )

    await after_(callback)


@router.callback_query(ClbDelete.filter(F.postfix == Postfix.confirm_booking))
async def delete_booking_confirm(callback: types.CallbackQuery, callback_data: ClbDelete):
    member = await api_members.get_member_by_tg_id(tg_id=callback.from_user.id)
    meeting = await api_meetings.get_meeting_by_pk(pk=callback_data.pk)
    btn_builder = TgButtonsUser.get_meeting(member=member, meeting=meeting)

    btn_builder = TgButtonsUser.add_booking_cancel(
        builder=btn_builder,
        pk=callback_data.pk,
        text="Да, отменить бронирование"
    )

    btn_builder.adjust(1)

    await replace_last_msg(
        callback=callback,
        text=text_msg.cancel_in_meeting_day(),
        btn_builder=btn_builder,
    )
    await after_(callback=callback)


@router.callback_query(ClbDelete.filter(F.postfix == Postfix.booking))
async def delete_booking(callback: types.CallbackQuery, callback_data: ClbDelete):
    meeting: Meeting = await api_meetings.get_meeting_by_pk(pk=callback_data.pk)
    member_ticket: Ticket = meeting.get_ticket_by_tg_id(tg_id=callback.from_user.id)
    if not member_ticket:
        return await send_answer(
            callback=callback,
            text=text_msg.cancel_already()
        )
    else:
        booking: Booking = member_ticket.get_booking()
        redis_key: str = db_redis.get_key_delete(name=Postfix.booking, pk=booking.get_pk())
        redis_info: Any = db_redis.get(redis_key)

        if redis_info:
            return await send_answer(
                callback=callback,
                text=text_msg.cancel_with_return_money()
            )
        elif booking.is_paid() or booking.is_user_confirm_paid():
            if meeting.is_meeting_today():
                text = text_msg.cancel_with_return_no_money()
            else:
                text = text_msg.cancel_with_return_money()

            meetings: list[Meeting] = await api_meetings.get_future_meetings()
            user_btn_builder = TgButtonsUser.get_meetings(meetings=meetings)
            await replace_last_msg(callback=callback, btn_builder=user_btn_builder, text=text)

            booking_pk: int = booking.get_pk()
            btn_builder_adm: InlineKeyboardBuilder = TgButtons.get_empty_builder()
            btn_builder_adm = TgButtonsAdmin.add_confirm_refund(
                builder=btn_builder_adm,
                pk=booking_pk
            )

            member: Member = member_ticket.get_booking_member()
            db_redis.set(
                key=redis_key,
                value=json.dumps({
                    "booking_pk": booking_pk,
                    "member_tg_id": member.get_tg_id(),
                    "user_chat_id": callback.from_user.id,
                    "msg_to_user_id": callback.message.message_id,
                })
            )
            if member.get_login():
                user_info: str = f"[{member.get_full_name()}]({member.get_link()})"
            else:
                user_info: str = member.get_full_name()

            notif_text: str = text_admins.confirm_cancel(
                user_info=user_info,
                meeting_info=meeting.get_name(),
            )

            await bot.send_message(
                chat_id=ADMIN_CHANEL_ID,
                text=notif_text,
                reply_markup=btn_builder_adm.as_markup(),
            )
        else:
            await api_bookings.delete_booking(booking)

            meetings: list[Meeting] = await api_meetings.get_future_meetings()
            if not meetings:
                text: str = text_msg.no_meetings_after_cancel()
            else:
                text: str = text_msg.meeting_dates_after_cancel()

            btn_builder: InlineKeyboardBuilder = TgButtonsUser.get_meetings(meetings=meetings)
            await replace_last_msg(
                callback=callback,
                text=text,
                btn_builder=btn_builder
            )

    await after_(callback=callback)


@router.callback_query(ClbConfirm.filter(F.postfix == Postfix.confirm_booking_adm))
async def confirm_booking_admin(callback: types.CallbackQuery, callback_data: ClbConfirm):
    redis_key: str = db_redis.get_key_confirm(name=Postfix.booking, pk=callback_data.pk)
    redis_info_json: str = db_redis.get(redis_key)

    if not redis_info_json:
        await replace_last_msg(
            callback=callback,
            text=callback.message.md_text + f"\n\n{text_admins.cancel_already()}",
            btn_builder=TgButtons.get_empty_builder(),
        )
        return await after_(callback)

    redis_info: dict = json.loads(redis_info_json)
    meeting_pk: int | None = redis_info.get("meeting_pk", None)
    member_tg_id: int | None = redis_info.get("member_tg_id", None)
    if not meeting_pk or not member_tg_id:
        await replace_last_msg(
            callback=callback,
            text=callback.message.md_text + f"\n\n{text_admins.error()}, не нашел в редисе PK брони или tg id юзера",
            btn_builder=TgButtons.get_empty_builder(),
        )
        return await after_(callback)

    booking: Booking = await api_bookings.get_booking_by_pk(pk=callback_data.pk)
    if not booking:
        await replace_last_msg(
            callback=callback,
            text=callback.message.md_text + f"\n\n{text_admins.error()}, не нашел бронь, может позже",
            btn_builder=TgButtons.get_empty_builder(),
        )
        return await after_(callback)

    booking.set_is_paid(True)
    _ = await api_bookings.update_booking(booking)
    db_redis.delete(redis_key)

    user_chat_id = redis_info.get("user_chat_id", None)
    msg_to_user_id = redis_info.get("msg_to_user_id", None)
    if not user_chat_id or not msg_to_user_id:
        # todo дописать отправку текста с ошибкой (подумать куда)
        pass
    else:
        member = booking.get_member()
        meeting = await api_meetings.get_meeting_by_pk(pk=meeting_pk)

        await bot.delete_message(
            chat_id=user_chat_id,
            message_id=msg_to_user_id
        )
        text = Service.get_meeting_text(
            member,
            meeting,
            False,
            f"\n{text_msg.booking_success_pay_success()}",
        )
        btn_builder = TgButtonsUser.get_meeting(member=member, meeting=meeting)
        btn_builder = TgButtonsUser.add_back(
            builder=btn_builder,
            callback=ClbShowList(postfix=Postfix.dates)
        )
        btn_builder.adjust(1)

        await bot.send_message(
            text=text,
            chat_id=user_chat_id,
            reply_markup=btn_builder.as_markup(),
        )

        await replace_last_msg(
            callback=callback,
            text=callback.message.md_text + f"\n\n{text_admins.booking_success()}",
            btn_builder=TgButtons.get_empty_builder()
        )

    await after_(callback)


@router.callback_query(ClbDelete.filter(F.postfix == Postfix.booking_adm))
async def delete_booking_admin(callback: types.CallbackQuery, callback_data: ClbDelete):
    # todo добавить кнопку в меню мои бронирования
    # todo подумать как сделать оповещения о бронировании и отмене
    booking_pk: int = callback_data.pk

    redis_key: str = db_redis.get_key_delete(name=Postfix.booking, pk=booking_pk)
    redis_info_json: str = db_redis.get(redis_key)

    if not redis_info_json:
        redis_key: str = db_redis.get_key_confirm(name=Postfix.booking, pk=booking_pk)
        redis_info_json: str = db_redis.get(redis_key)

    if not redis_info_json:
        await bot.send_message(
            chat_id=ADMIN_CHANEL_ID,
            text=f"{text_admins.error()}, кароч в redis нет инфы про отмену",
        )
        return await after_(callback)

    redis_info: dict = json.loads(redis_info_json)
    member_tg_id: int | None = redis_info.get("member_tg_id", None)
    if not booking_pk or not member_tg_id:
        await bot.send_message(
            chat_id=ADMIN_CHANEL_ID,
            text=f"{text_admins.error()}, не нашел PK брони или tg id юзера, может позже",
        )
        return await after_(callback)

    booking: Booking = await api_bookings.get_booking_by_pk(pk=booking_pk)
    if not booking:
        await bot.send_message(
            chat_id=ADMIN_CHANEL_ID,
            text=f"{text_admins.error()}, не нашел бронь, может позже",
        )
        return await after_(callback)

    db_redis.delete(redis_key)
    await api_bookings.delete_booking(booking)

    user_chat_id = redis_info.get("user_chat_id", None)
    msg_to_user_id = redis_info.get("msg_to_user_id", None)
    if not user_chat_id or not msg_to_user_id:
        # todo дописать отправку текста с ошибкой (подумать куда)
        pass
    else:
        await bot.delete_message(
            chat_id=user_chat_id,
            message_id=msg_to_user_id
        )

    if booking.is_paid():
        text = text_admins.booking_cancel_success()
        usr_text = text_msg.cancel_with_return_success()
    else:
        text = text_admins.booking_cancel_success_check_money()
        usr_text = text_msg.cancel_by_admin()

    meetings = await api_meetings.get_future_meetings()
    btn_builder = TgButtonsUser.get_meetings(meetings)
    await bot.send_message(
        chat_id=member_tg_id,
        text=usr_text,
        reply_markup=btn_builder.as_markup()
    )

    await replace_last_msg(
        callback=callback,
        btn_builder=TgButtons.get_empty_builder(),
        text=callback.message.md_text + f"\n\n{text}"
    )

    await after_(callback)


async def replace_last_msg(callback: types.CallbackQuery, text: str, btn_builder: InlineKeyboardBuilder):
    await bot.edit_message_text(
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=text,
        reply_markup=btn_builder.as_markup(),
    )


async def send_answer(callback: types.CallbackQuery, text: str):
    await callback.answer(text=text, show_alert=True)
    await after_(callback=callback)


async def after_(callback: types.CallbackQuery) -> None:
    await bot.answer_callback_query(callback.id)


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
