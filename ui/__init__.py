"""ui — Modal UI framework.

Provides a ``ModalStack`` that manages layered modal overlays
(inventory, transfer, shop, dialog, etc.).  Each modal is a
self-contained ``Modal`` subclass with its own update / input / draw.
"""

from ui.modal import Modal, ModalStack
from ui.commands import CloseModal, HealPlayer, OpenTrade, SetFlag, UICommand
from ui.inventory_modal import InventoryModal
from ui.transfer_modal import TransferModal
from ui.dialogue_modal import DialogueModal

__all__ = [
    "Modal", "ModalStack",
    "CloseModal", "HealPlayer", "OpenTrade", "SetFlag", "UICommand",
    "InventoryModal", "TransferModal", "DialogueModal",
]
