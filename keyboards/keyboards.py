from maxo.utils.builders import KeyboardBuilder

from lexicon.lexicon import BUTTON_LEXICON


def create_keyboards(*buttons: str):
    builder = KeyboardBuilder()
    for button in buttons:
        builder.add_message(text=button).adjust(1)
    return builder.build()
