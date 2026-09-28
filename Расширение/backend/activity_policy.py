"""One reward policy for presence, engagement, XP and case eligibility."""
from config import ACTIVE_WINDOW, ENGAGED_WINDOW, REDUCED_WINDOW

# 50%, а не 25: доля пассивного зрителя — продуктовое число, и меняет его
# владелец. 06.09 оно уехало на 25 вместе с техническими правками трека
# активности и было возвращено его решением в тот же день.
PASSIVE_REWARD_PERCENT = 50


def reward_status(presence_age, interaction_age):
    if presence_age is None or presence_age >= REDUCED_WINDOW:
        return "offline"
    if (presence_age < ACTIVE_WINDOW and interaction_age is not None
            and 0 <= interaction_age < ENGAGED_WINDOW):
        return "active"
    return "reduced"


def reward_percent(status):
    return 100 if status == "active" else PASSIVE_REWARD_PERCENT if status == "reduced" else 0
