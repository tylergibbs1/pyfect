"""Anthropic's provider-defined tools (Effect's ``AnthropicTool``).

Each constant is a tool's constructor: call it with the tool's arguments
to put it in a toolkit. Tools Anthropic runs (code execution, web search,
web fetch, tool search) need no handler; the client tools (bash, the text
editor, computer use, memory) do::

    kit = toolkit.make(tool.WebSearch_20250305(max_uses=3), tool.Bash_20250124())

Arguments use Effect's camelCase names (``maxUses``, ``displayWidthPx``)
as keywords or a mapping. The results of server tools are Anthropic's
JSON blocks, unchanged.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from pyfect import schema as S
from pyfect.ai import tool as T
from pyfect.context import Reference

_BLOCK = S.Record(S.String, S.Unknown)
"""A JSON block Anthropic returns, kept whole."""

# Bash ----------------------------------------------------------------------------------


class BashParameters(TypedDict):
    command: str
    restart: NotRequired[bool]


Bash_20241022 = T.provider_defined(
    id="anthropic.bash_20241022",
    custom_name="AnthropicBash",
    provider_name="bash",
    requires_handler=True,
    parameters=S.Struct(BashParameters),
    success=S.String,
)
Bash_20250124 = T.provider_defined(
    id="anthropic.bash_20250124",
    custom_name="AnthropicBash",
    provider_name="bash",
    requires_handler=True,
    parameters=S.Struct(BashParameters),
    success=S.String,
)

# Code execution ------------------------------------------------------------------------


class CodeExecutionProgrammaticToolCall(TypedDict):
    type: Literal["programmatic-tool-call"]
    code: str


class CodeExecutionBashCommand(TypedDict):
    type: Literal["bash_code_execution"]
    command: str


class CodeExecutionTextEditorView(TypedDict):
    type: Literal["text_editor_code_execution"]
    command: Literal["view"]
    path: str


class CodeExecutionTextEditorCreate(TypedDict):
    type: Literal["text_editor_code_execution"]
    command: Literal["create"]
    path: str
    file_text: NotRequired[str | None]


class CodeExecutionTextEditorStrReplace(TypedDict):
    type: Literal["text_editor_code_execution"]
    command: Literal["str_replace"]
    path: str
    old_str: str
    new_str: str


class CodeExecution_20250825_Parameters(TypedDict):
    code: str


_CODE_EXECUTION_PARAMETERS = S.Union(
    S.Struct(CodeExecutionProgrammaticToolCall),
    S.Struct(CodeExecutionBashCommand),
    S.Struct(CodeExecutionTextEditorView),
    S.Struct(CodeExecutionTextEditorCreate),
    S.Struct(CodeExecutionTextEditorStrReplace),
)

CodeExecution_20250522 = T.provider_defined(
    id="anthropic.code_execution_20250522",
    custom_name="AnthropicCodeExecution",
    provider_name="code_execution",
    parameters=_CODE_EXECUTION_PARAMETERS,
    success=_BLOCK,
    failure=_BLOCK,
)
CodeExecution_20250825 = T.provider_defined(
    id="anthropic.code_execution_20250825",
    custom_name="AnthropicCodeExecution",
    provider_name="code_execution",
    # Effect 4.1.2 gives this version only `{code}` (and 20250522 the sub-tool
    # calls), but 20250825 is the version whose calls are the sub-tools.
    parameters=_CODE_EXECUTION_PARAMETERS,
    success=_BLOCK,
    failure=_BLOCK,
)

# Computer use --------------------------------------------------------------------------

type Coordinate = tuple[int, int]
type Region = tuple[int, int, int, int]


class ComputerUseArgs(TypedDict):
    displayWidthPx: int
    displayHeightPx: int
    displayNumber: NotRequired[int]


class ComputerUse_20251124_Args(ComputerUseArgs):
    enableZoom: NotRequired[bool]


class KeyAction(TypedDict):
    action: Literal["key"]
    text: str


class LeftClickAction(TypedDict):
    action: Literal["left_click"]
    coordinate: NotRequired[Coordinate]


class MouseMoveAction(TypedDict):
    action: Literal["mouse_move"]
    coordinate: Coordinate


class ScreenshotAction(TypedDict):
    action: Literal["screenshot"]


class TypeAction(TypedDict):
    action: Literal["type"]
    text: str


class DoubleClickAction(TypedDict):
    action: Literal["double_click"]
    coordinate: NotRequired[Coordinate]


class HoldKeyAction(TypedDict):
    action: Literal["hold_key"]
    text: str
    duration: float


class LeftClickDragAction(TypedDict):
    action: Literal["left_click_drag"]
    start_coordinate: Coordinate
    coordinate: Coordinate


class LeftMouseDownAction(TypedDict):
    action: Literal["left_mouse_down"]
    coordinate: NotRequired[Coordinate]


class LeftMouseUpAction(TypedDict):
    action: Literal["left_mouse_up"]
    coordinate: NotRequired[Coordinate]


class MiddleClickAction(TypedDict):
    action: Literal["middle_click"]
    coordinate: NotRequired[Coordinate]


class RightClickAction(TypedDict):
    action: Literal["right_click"]
    coordinate: NotRequired[Coordinate]


class ScrollAction(TypedDict):
    action: Literal["scroll"]
    coordinate: NotRequired[Coordinate]
    scroll_direction: Literal["up", "down", "left", "right"]
    scroll_amount: int


class TripleClickAction(TypedDict):
    action: Literal["triple_click"]
    coordinate: NotRequired[Coordinate]


class WaitAction(TypedDict):
    action: Literal["wait"]
    duration: float


class ZoomAction(TypedDict):
    action: Literal["zoom"]
    region: Region


_ACTIONS_20241022 = (
    S.Struct(KeyAction),
    S.Struct(LeftClickAction),
    S.Struct(MouseMoveAction),
    S.Struct(ScreenshotAction),
    S.Struct(TypeAction),
)
_ACTIONS_20250124 = (
    *_ACTIONS_20241022,
    S.Struct(DoubleClickAction),
    S.Struct(HoldKeyAction),
    S.Struct(LeftClickDragAction),
    S.Struct(LeftMouseDownAction),
    S.Struct(LeftMouseUpAction),
    S.Struct(MiddleClickAction),
    S.Struct(RightClickAction),
    S.Struct(ScrollAction),
    S.Struct(TripleClickAction),
    S.Struct(WaitAction),
)

type ComputerUse_20241022_Action = (
    KeyAction | LeftClickAction | MouseMoveAction | ScreenshotAction | TypeAction
)
type ComputerUse_20250124_Action = (
    ComputerUse_20241022_Action
    | DoubleClickAction
    | HoldKeyAction
    | LeftClickDragAction
    | LeftMouseDownAction
    | LeftMouseUpAction
    | MiddleClickAction
    | RightClickAction
    | ScrollAction
    | TripleClickAction
    | WaitAction
)
type ComputerUse_20251124_Action = ComputerUse_20250124_Action | ZoomAction

_COMPUTER_20241022: S.Codec[ComputerUse_20241022_Action, Any, Any, Any] = S.Union(
    *_ACTIONS_20241022
)
_COMPUTER_20250124: S.Codec[ComputerUse_20250124_Action, Any, Any, Any] = S.Union(
    *_ACTIONS_20250124
)
_COMPUTER_20251124: S.Codec[ComputerUse_20251124_Action, Any, Any, Any] = S.Union(
    *_ACTIONS_20250124, S.Struct(ZoomAction)
)

ComputerUse_20241022 = T.provider_defined(
    id="anthropic.computer_use_20241022",
    custom_name="AnthropicComputerUse",
    provider_name="computer",
    requires_handler=True,
    args=S.Struct(ComputerUseArgs),
    parameters=_COMPUTER_20241022,
    success=S.String,
)
ComputerUse_20250124 = T.provider_defined(
    id="anthropic.computer_20250124",
    custom_name="AnthropicComputerUse",
    provider_name="computer",
    requires_handler=True,
    args=S.Struct(ComputerUseArgs),
    parameters=_COMPUTER_20250124,
    success=S.String,
)
ComputerUse_20251124 = T.provider_defined(
    id="anthropic.computer_20251124",
    custom_name="AnthropicComputerUse",
    provider_name="computer",
    requires_handler=True,
    args=S.Struct(ComputerUse_20251124_Args),
    parameters=_COMPUTER_20251124,
    success=S.String,
)

# Memory and the text editor ------------------------------------------------------------

type ViewRange = tuple[int, int]


class MemoryCreateCommand(TypedDict):
    command: Literal["create"]
    path: str
    file_text: str


class MemoryDeleteCommand(TypedDict):
    command: Literal["delete"]
    path: str


class MemoryInsertCommand(TypedDict):
    command: Literal["insert"]
    path: str
    insert_line: int
    insert_text: str


class MemoryRenameCommand(TypedDict):
    command: Literal["rename"]
    old_path: str
    new_path: str


class StrReplaceCommand(TypedDict):
    command: Literal["str_replace"]
    path: str
    old_str: str
    new_str: str


class ViewCommand(TypedDict):
    command: Literal["view"]
    path: str
    view_range: NotRequired[ViewRange]


type MemoryCommand = (
    MemoryCreateCommand
    | MemoryDeleteCommand
    | MemoryInsertCommand
    | MemoryRenameCommand
    | StrReplaceCommand
    | ViewCommand
)

_MEMORY: S.Codec[MemoryCommand, Any, Any, Any] = S.Union(
    S.Struct(MemoryCreateCommand),
    S.Struct(MemoryDeleteCommand),
    S.Struct(MemoryInsertCommand),
    S.Struct(MemoryRenameCommand),
    S.Struct(StrReplaceCommand),
    S.Struct(ViewCommand),
)

Memory_20250818 = T.provider_defined(
    id="anthropic.memory_20250818",
    custom_name="AnthropicMemory",
    provider_name="memory",
    requires_handler=True,
    parameters=_MEMORY,
    success=S.String,
)


class CreateCommand(TypedDict):
    command: Literal["create"]
    path: str
    file_text: str


class InsertCommand(TypedDict):
    """The insert command of ``text_editor_20241022`` and
    ``text_editor_20250124``; later versions send ``InsertTextCommand``."""

    command: Literal["insert"]
    path: str
    insert_line: int
    new_str: str


class InsertTextCommand(TypedDict):
    """The insert command of ``text_editor_20250429`` and
    ``text_editor_20250728``."""

    command: Literal["insert"]
    path: str
    insert_line: int
    insert_text: str


class UndoEditCommand(TypedDict):
    command: Literal["undo_edit"]
    path: str


class TextEditorArgs(TypedDict):
    max_characters: NotRequired[int]


type StrReplaceBasedEditCommand = (
    ViewCommand | CreateCommand | StrReplaceCommand | InsertTextCommand
)
type StrReplaceEditorCommand = (
    ViewCommand | CreateCommand | StrReplaceCommand | InsertCommand | UndoEditCommand
)

_EDIT = (S.Struct(ViewCommand), S.Struct(CreateCommand), S.Struct(StrReplaceCommand))
_STR_REPLACE_EDITOR: S.Codec[StrReplaceEditorCommand, Any, Any, Any] = S.Union(
    *_EDIT, S.Struct(InsertCommand), S.Struct(UndoEditCommand)
)
_STR_REPLACE_BASED_EDIT: S.Codec[StrReplaceBasedEditCommand, Any, Any, Any] = S.Union(
    *_EDIT, S.Struct(InsertTextCommand)
)

TextEditor_20241022 = T.provider_defined(
    id="anthropic.text_editor_20241022",
    custom_name="AnthropicTextEditor",
    provider_name="str_replace_editor",
    requires_handler=True,
    parameters=_STR_REPLACE_EDITOR,
    success=S.String,
)
TextEditor_20250124 = T.provider_defined(
    id="anthropic.text_editor_20250124",
    custom_name="AnthropicTextEditor",
    provider_name="str_replace_editor",
    requires_handler=True,
    parameters=_STR_REPLACE_EDITOR,
    success=S.String,
)
TextEditor_20250429 = T.provider_defined(
    id="anthropic.text_editor_20250429",
    custom_name="AnthropicTextEditor",
    provider_name="str_replace_based_edit_tool",
    requires_handler=True,
    args=S.Struct(TextEditorArgs),
    parameters=_STR_REPLACE_BASED_EDIT,
    success=S.String,
)
TextEditor_20250728 = T.provider_defined(
    id="anthropic.text_editor_20250728",
    custom_name="AnthropicTextEditor",
    provider_name="str_replace_based_edit_tool",
    requires_handler=True,
    args=S.Struct(TextEditorArgs),
    parameters=_STR_REPLACE_BASED_EDIT,
    success=S.String,
)

# Web search, web fetch and tool search ----------------------------------------------------


class WebSearchUserLocation(TypedDict):
    type: Literal["approximate"]
    city: NotRequired[str]
    region: NotRequired[str]
    country: NotRequired[str]
    timezone: NotRequired[str]


class WebSearch_20250305_Args(TypedDict, total=False):
    maxUses: int
    allowedDomains: list[str]
    blockedDomains: list[str]
    userLocation: WebSearchUserLocation


class QueryParameters(TypedDict):
    query: str


WebSearch_20250305 = T.provider_defined(
    id="anthropic.web_search_20250305",
    custom_name="AnthropicWebSearch",
    provider_name="web_search",
    args=S.Struct(WebSearch_20250305_Args),
    parameters=S.Struct(QueryParameters),
    success=S.Array(_BLOCK),
    failure=_BLOCK,
)


class WebFetchCitationsConfig(TypedDict):
    enabled: bool


class WebFetch_20250910_Args(TypedDict, total=False):
    maxUses: int
    allowedDomains: list[str]
    blockedDomains: list[str]
    citations: WebFetchCitationsConfig
    maxContentTokens: int


class WebFetchParameters(TypedDict):
    url: str


WebFetch_20250910 = T.provider_defined(
    id="anthropic.web_fetch_20250910",
    custom_name="AnthropicWebFetch",
    provider_name="web_fetch",
    args=S.Struct(WebFetch_20250910_Args),
    parameters=S.Struct(WebFetchParameters),
    success=_BLOCK,
    failure=_BLOCK,
)


class ToolSearchRegexParameters(TypedDict):
    """A Python ``re.search`` pattern of at most 200 characters; ``limit``
    caps the tools returned (1 to 10,000, default 5)."""

    pattern: str
    limit: NotRequired[int]


class ToolSearchBM25Parameters(TypedDict):
    """A natural-language query over tool names, descriptions and
    arguments; ``limit`` caps the tools returned (1 to 10,000, default 5)."""

    query: str
    limit: NotRequired[int]


class DeferLoading(Reference[bool], key="@effect/ai-anthropic/AnthropicTool/DeferLoading"):
    """Annotate a user-defined tool with ``True`` to send it with
    ``defer_loading``: Claude only sees it once tool search finds it.
    Anthropic needs at least one tool not deferred (normally the tool
    search tool); provider-defined tools ignore it::

        kit = toolkit.make(
            list_contacts.annotate(tool.DeferLoading, True), tool.ToolSearchBM25_20251119()
        )
    """

    @classmethod
    def default(cls) -> bool:
        return False


ToolSearchRegex_20251119 = T.provider_defined(
    id="anthropic.tool_search_tool_regex_20251119",
    custom_name="AnthropicToolSearchRegex",
    provider_name="tool_search_tool_regex",
    parameters=S.Struct(ToolSearchRegexParameters),
    success=S.Array(_BLOCK),
    failure=_BLOCK,
)
ToolSearchBM25_20251119 = T.provider_defined(
    id="anthropic.tool_search_tool_bm25_20251119",
    custom_name="AnthropicToolSearchBM25",
    provider_name="tool_search_tool_bm25",
    parameters=S.Struct(ToolSearchBM25Parameters),
    success=S.Array(_BLOCK),
    failure=_BLOCK,
)

__all__ = [
    "BashParameters",
    "Bash_20241022",
    "Bash_20250124",
    "CodeExecutionBashCommand",
    "CodeExecutionProgrammaticToolCall",
    "CodeExecutionTextEditorCreate",
    "CodeExecutionTextEditorStrReplace",
    "CodeExecutionTextEditorView",
    "CodeExecution_20250522",
    "CodeExecution_20250825",
    "CodeExecution_20250825_Parameters",
    "ComputerUseArgs",
    "ComputerUse_20241022",
    "ComputerUse_20241022_Action",
    "ComputerUse_20250124",
    "ComputerUse_20250124_Action",
    "ComputerUse_20251124",
    "ComputerUse_20251124_Action",
    "ComputerUse_20251124_Args",
    "Coordinate",
    "CreateCommand",
    "DeferLoading",
    "DoubleClickAction",
    "HoldKeyAction",
    "InsertCommand",
    "InsertTextCommand",
    "KeyAction",
    "LeftClickAction",
    "LeftClickDragAction",
    "LeftMouseDownAction",
    "LeftMouseUpAction",
    "MemoryCommand",
    "MemoryCreateCommand",
    "MemoryDeleteCommand",
    "MemoryInsertCommand",
    "MemoryRenameCommand",
    "Memory_20250818",
    "MiddleClickAction",
    "MouseMoveAction",
    "QueryParameters",
    "Region",
    "RightClickAction",
    "ScreenshotAction",
    "ScrollAction",
    "StrReplaceBasedEditCommand",
    "StrReplaceCommand",
    "StrReplaceEditorCommand",
    "TextEditorArgs",
    "TextEditor_20241022",
    "TextEditor_20250124",
    "TextEditor_20250429",
    "TextEditor_20250728",
    "ToolSearchBM25Parameters",
    "ToolSearchBM25_20251119",
    "ToolSearchRegexParameters",
    "ToolSearchRegex_20251119",
    "TripleClickAction",
    "TypeAction",
    "UndoEditCommand",
    "ViewCommand",
    "ViewRange",
    "WaitAction",
    "WebFetchCitationsConfig",
    "WebFetchParameters",
    "WebFetch_20250910",
    "WebFetch_20250910_Args",
    "WebSearchUserLocation",
    "WebSearch_20250305",
    "WebSearch_20250305_Args",
    "ZoomAction",
]
