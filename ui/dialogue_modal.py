"""ui/dialogue_modal.py — Dialogue conversation modal."""

from __future__ import annotations
import pygame
from ui.modal import Modal
from ui.commands import CloseModal, OpenTrade, SetFlag, UICommand
from ui.helpers import draw_overlay


class DialogueModal(Modal):
    """Displays an NPC dialogue tree and lets the player choose responses."""

    def __init__(
        self,
        tree: dict,
        npc_name: str = "NPC",
        npc_eid: int = -1,
        quest_log=None,
        start_node: str = "root",
    ):
        self._tree = tree
        self._npc_name = npc_name
        self._npc_eid = npc_eid
        self._quest_log = quest_log
        self._node_id = start_node
        self._cursor = 0
        self._choices: list[dict] = []
        self._npc_text = ""
        self._choice_rects: list[pygame.Rect] = []
        self._advance_to(start_node)

    # ── node navigation ──────────────────────────────────────────────

    def _advance_to(self, node_id: str):
        node = self._tree.get(node_id)
        if node is None:
            self._npc_text = "(End of conversation.)"
            self._choices = [{"label": "[Leave]", "action": "close"}]
            self._cursor = 0
            return
        self._node_id = node_id
        self._npc_text = node.get("text", "...")
        raw = node.get("choices", [{"label": "[Leave]", "action": "close"}])
        self._choices = [c for c in raw if self._check_condition(c)]
        self._cursor = 0

    def _check_condition(self, choice: dict) -> bool:
        cond = choice.get("condition")
        if cond is None:
            return True
        if self._quest_log is None:
            return True
        if cond.startswith("!"):
            return not self._quest_log.has_flag(cond[1:])
        return self._quest_log.has_flag(cond)

    def _select_choice(self) -> list[UICommand]:
        if not self._choices:
            return [CloseModal()]
        choice = self._choices[self._cursor]
        cmds: list[UICommand] = []

        action = choice.get("action", "")
        if action == "close":
            cmds.append(CloseModal())
            return cmds
        elif action == "open_trade":
            cmds.append(OpenTrade(npc_eid=self._npc_eid))
            return cmds
        elif action.startswith("set_flag:"):
            parts = action.split(":", 2)
            flag = parts[1] if len(parts) > 1 else ""
            value = parts[2] if len(parts) > 2 else True
            cmds.append(SetFlag(flag=flag, value=value))

        next_node = choice.get("next")
        if next_node:
            self._advance_to(next_node)
        elif not cmds:
            cmds.append(CloseModal())
        return cmds

    # ── Modal interface ──────────────────────────────────────────────

    def update(self, dt: float):
        pass

    def handle_event(self, event: pygame.event.Event) -> list[UICommand]:
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_w, pygame.K_UP):
                self._cursor = max(0, self._cursor - 1)
            elif event.key in (pygame.K_s, pygame.K_DOWN):
                self._cursor = min(len(self._choices) - 1, self._cursor + 1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_e):
                return self._select_choice()
            elif event.key == pygame.K_ESCAPE:
                return [CloseModal()]
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in enumerate(self._choice_rects):
                if rect.collidepoint(event.pos):
                    self._cursor = i
                    return self._select_choice()
        elif event.type == pygame.MOUSEMOTION:
            for i, rect in enumerate(self._choice_rects):
                if rect.collidepoint(event.pos):
                    self._cursor = i
                    break
        return []

    def draw(self, surface: pygame.Surface, app):
        draw_overlay(surface, alpha=160)
        sw, sh = surface.get_size()

        box_w = min(600, sw - 40)
        box_h = min(400, sh - 40)
        box_x = (sw - box_w) // 2
        box_y = (sh - box_h) // 2

        # Background
        pygame.draw.rect(surface, (30, 30, 35), (box_x, box_y, box_w, box_h))
        pygame.draw.rect(surface, (100, 100, 110), (box_x, box_y, box_w, box_h), 2)

        font = pygame.font.SysFont("consolas", 16)

        # NPC name
        name_surf = font.render(self._npc_name, True, (255, 220, 100))
        surface.blit(name_surf, (box_x + 12, box_y + 8))

        # Separator
        pygame.draw.line(
            surface, (80, 80, 90),
            (box_x + 8, box_y + 30), (box_x + box_w - 8, box_y + 30),
        )

        # NPC text
        y = box_y + 40
        for line in self._npc_text.split("\n"):
            text_surf = font.render(line, True, (220, 220, 220))
            surface.blit(text_surf, (box_x + 16, y))
            y += 22

        # Separator before choices
        y += 10
        pygame.draw.line(
            surface, (60, 60, 70),
            (box_x + 8, y), (box_x + box_w - 8, y),
        )
        y += 10

        # Choices
        self._choice_rects = []
        for i, choice in enumerate(self._choices):
            selected = i == self._cursor
            color = (255, 255, 255) if selected else (160, 160, 160)
            prefix = "> " if selected else "  "
            label = prefix + choice.get("label", "...")
            text_surf = font.render(label, True, color)
            rect = pygame.Rect(box_x + 12, y, box_w - 24, 24)
            if selected:
                pygame.draw.rect(surface, (50, 50, 60), rect)
            surface.blit(text_surf, (box_x + 16, y + 2))
            self._choice_rects.append(rect)
            y += 26
