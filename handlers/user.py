from maxo.integrations.magic_filter import MagicFilter
from magic_filter import F
from maxo import Router
from maxo.routing.filters import CommandStart,Command
from maxo.routing.updates import MessageCreated, MessageCallback
from maxo.utils.facades import MessageCreatedFacade,MessageCallbackFacade
from maxo.types.message import Message
from maxo.fsm import StateFilter
from maxo.routing.ctx import Ctx
from maxo.types.photo_attachment_request import PhotoAttachmentRequest
from maxo.types.video_attachment_request import VideoAttachmentRequest

from llm.llm import ask_giga_chat_async
from lexicon.lexicon import COMMAND_LEXICON,OTHER_LEXICON
from keyboards.inlinekeyboards import create_inline_keyboards
user_router = Router(name='user')



# /start — приветственное сообщение с кнопками
@user_router.message_created(CommandStart())
async def start_handler(update: MessageCreated, facade: MessageCreatedFacade) -> None:
    keyboard = create_inline_keyboards(
        'sign_up',
        'consultation',
        'view_media',
    )
    await facade.answer_text(
        text=COMMAND_LEXICON['/start'],
        keyboard=keyboard

    )

# Обработка нажатия кнопки "Записаться на курс"
@user_router.message_callback(MagicFilter(F.payload == 'sign_up'))
async def sign_up_handler(callback: MessageCallback, facade: MessageCallbackFacade) -> None:
    await facade.answer_text(text=OTHER_LEXICON['sign up for a course'])


# Обработка нажатия кнопки "Консультация"
@user_router.message_callback(MagicFilter(F.payload == 'consultation'))
async def consultation_handler(callback: MessageCallback, facade: MessageCallbackFacade) -> None:
    await facade.answer_text(text=OTHER_LEXICON['consultation'])


# Обработка нажатия кнопки "Посмотреть фото и видео с занятий"
@user_router.message_callback(MagicFilter(F.payload == 'view_media'))
async def view_media_handler(callback:MessageCallback, facade: MessageCallbackFacade,ctx:Ctx) -> None:
    redis_client = ctx.get('redis_client')
    token_photo_list = await redis_client.lrange('photos',0,-1)
    token_video_list = await redis_client.lrange('videos',0,-1)
    media = []

    if len(token_photo_list) >0:
        for token in token_photo_list:
            if isinstance(token,bytes):
                token = token.decode()
            media.append(PhotoAttachmentRequest.factory(token=str(token)))

    if len(token_video_list) > 0:
        for token in token_video_list:
            if isinstance(token,bytes):
                token = token.decode()
            media.append(VideoAttachmentRequest.factory(token=str(token)))

    # Если в списке media от 1 до 10 элементов — отправляем их как медиа-группу
    # Telegram API позволяет отправлять одновременно максимум 10 и минимум 2 элементов как группу
    if 1 < len(media) <=10:
        await facade.send_media(media=media)

    # если больше 10 - разбиваем на части
    elif len(media) > 10:
        for i in range(0,len(media),10):
            await facade.send_media(media=media[i:i+10])

    else:
        await facade.answer_text('Нет медиа для отображения.')





@user_router.message_created(MagicFilter(F.text) & StateFilter(None))
async def llm_handler(update: MessageCreated, facade: MessageCreatedFacade) -> None:
    user_id = update.message.recipient.user_id
    response = await ask_giga_chat_async(update.text,str(user_id))
    keyboard = create_inline_keyboards(
        'sign_up',
        'view_media',
    )
    await facade.answer_text(text=response,keyboard=keyboard)

# Обработка сообщений, которые не являются текстом
@user_router.message()
async def default_response(update: MessageCreated, facade:MessageCreatedFacade):
    await facade.answer_text('Извините, я отвечаю только на текстовые сообщения')
