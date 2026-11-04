"""The schemas of the OpenRouter API (Effect's ``Generated.ts``), generated from
Effect's module by ``scripts/gen_ai_schemas.py``: rerun it after an
update, do not edit. Each schema has Effect's name, its checks and its
annotations; its type is the name of the same name in ``types``::

    from pyfect.ai.openrouter import generated
    from pyfect.ai.openrouter.generated import types

    value: types.ChatResult = S.decode_unknown_sync(generated.ChatResult)(json)
"""

# pyright: reportPrivateUsage=false, reportUnusedImport=false
from __future__ import annotations

from pyfect.ai.openrouter.generated._schemas_0 import AABenchmarkEntry as AABenchmarkEntry
from pyfect.ai.openrouter.generated._schemas_0 import ActivityItem as ActivityItem
from pyfect.ai.openrouter.generated._schemas_0 import AdvisorNestedTool as AdvisorNestedTool
from pyfect.ai.openrouter.generated._schemas_0 import AdvisorReasoning as AdvisorReasoning
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicAdvisorToolResult as AnthropicAdvisorToolResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicAllowedCallers as AnthropicAllowedCallers
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBase64PdfSource as AnthropicBase64PdfSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBashCodeExecutionOutput as AnthropicBashCodeExecutionOutput
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBashCodeExecutionToolResultError as AnthropicBashCodeExecutionToolResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCacheControlTtl as AnthropicCacheControlTtl
from pyfect.ai.openrouter.generated._schemas_0 import Objects_ as Objects_
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationCharLocation as AnthropicCitationCharLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationCharLocationParam as AnthropicCitationCharLocationParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationContentBlockLocation as AnthropicCitationContentBlockLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationContentBlockLocationParam as AnthropicCitationContentBlockLocationParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationPageLocation as AnthropicCitationPageLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationPageLocationParam as AnthropicCitationPageLocationParam
from pyfect.ai.openrouter.generated._schemas_0 import Objects_1 as Objects_1
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationSearchResultLocation as AnthropicCitationSearchResultLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationSearchResultLocationParam as AnthropicCitationSearchResultLocationParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationWebSearchResultLocation as AnthropicCitationWebSearchResultLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationWebSearchResultLocationParam as AnthropicCitationWebSearchResultLocationParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecution20250825Caller as AnthropicCodeExecution20250825Caller
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecution20260120Caller as AnthropicCodeExecution20260120Caller
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecutionOutput as AnthropicCodeExecutionOutput
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCompactionBlock as AnthropicCompactionBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicContainer as AnthropicContainer
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicContainerUpload as AnthropicContainerUpload
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicDirectCaller as AnthropicDirectCaller
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicFileDocumentSource as AnthropicFileDocumentSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicImageMimeType as AnthropicImageMimeType
from pyfect.ai.openrouter.generated._schemas_0 import Objects_2 as Objects_2
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicInputTokensTrigger as AnthropicInputTokensTrigger
from pyfect.ai.openrouter.generated._schemas_0 import Objects_3 as Objects_3
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicOutputTokensDetails as AnthropicOutputTokensDetails
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicPlainTextSource as AnthropicPlainTextSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicRedactedThinkingBlock as AnthropicRedactedThinkingBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicRefusalStopDetails as AnthropicRefusalStopDetails
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicServerToolErrorCode as AnthropicServerToolErrorCode
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicServerToolUsage as AnthropicServerToolUsage
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicServiceTier as AnthropicServiceTier
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicSpeed as AnthropicSpeed
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionCreateResult as AnthropicTextEditorCodeExecutionCreateResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionStrReplaceResult as AnthropicTextEditorCodeExecutionStrReplaceResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionToolResultError as AnthropicTextEditorCodeExecutionToolResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionViewResult as AnthropicTextEditorCodeExecutionViewResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicThinkingBlock as AnthropicThinkingBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicThinkingDisplay as AnthropicThinkingDisplay
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicThinkingTurns as AnthropicThinkingTurns
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolReference as AnthropicToolReference
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolUsesKeep as AnthropicToolUsesKeep
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolUsesTrigger as AnthropicToolUsesTrigger
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicUrlImageSource as AnthropicUrlImageSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicUrlPdfSource as AnthropicUrlPdfSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebFetchToolResultError as AnthropicWebFetchToolResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebSearchResult as AnthropicWebSearchResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebSearchResultBlockParam as AnthropicWebSearchResultBlockParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebSearchToolResultError as AnthropicWebSearchToolResultError
from pyfect.ai.openrouter.generated._schemas_0 import Objects_4 as Objects_4
from pyfect.ai.openrouter.generated._schemas_0 import ApiErrorType as ApiErrorType
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallOperationDiffDeltaEvent as ApplyPatchCallOperationDiffDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallOperationDiffDoneEvent as ApplyPatchCallOperationDiffDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallOutputItem as ApplyPatchCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallStatus as ApplyPatchCallStatus
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCreateFileOperation as ApplyPatchCreateFileOperation
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchDeleteFileOperation as ApplyPatchDeleteFileOperation
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchEngineEnum as ApplyPatchEngineEnum
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchServerTool as ApplyPatchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchUpdateFileOperation as ApplyPatchUpdateFileOperation
from pyfect.ai.openrouter.generated._schemas_0 import AppRankingsItem as AppRankingsItem
from pyfect.ai.openrouter.generated._schemas_0 import AutoBetaRouterPlugin as AutoBetaRouterPlugin
from pyfect.ai.openrouter.generated._schemas_0 import AutoRouterPlugin as AutoRouterPlugin
from pyfect.ai.openrouter.generated._schemas_0 import BadGatewayResponseErrorData as BadGatewayResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import BadRequestResponseErrorData as BadRequestResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import BaseCustomToolCallInputDeltaEvent as BaseCustomToolCallInputDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseCustomToolCallInputDoneEvent as BaseCustomToolCallInputDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseErrorEvent as BaseErrorEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseFunctionCallArgsDeltaEvent as BaseFunctionCallArgsDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseFunctionCallArgsDoneEvent as BaseFunctionCallArgsDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseReasoningDeltaEvent as BaseReasoningDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseReasoningDoneEvent as BaseReasoningDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseReasoningSummaryTextDeltaEvent as BaseReasoningSummaryTextDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseReasoningSummaryTextDoneEvent as BaseReasoningSummaryTextDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseRefusalDeltaEvent as BaseRefusalDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseRefusalDoneEvent as BaseRefusalDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import BashServerToolEngine as BashServerToolEngine
from pyfect.ai.openrouter.generated._schemas_0 import BooleanCapability as BooleanCapability
from pyfect.ai.openrouter.generated._schemas_0 import BulkAddWorkspaceMembersRequest as BulkAddWorkspaceMembersRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkAssignKeysRequest as BulkAssignKeysRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkAssignKeysResponse as BulkAssignKeysResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkAssignMembersRequest as BulkAssignMembersRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkAssignMembersResponse as BulkAssignMembersResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkRemoveWorkspaceMembersRequest as BulkRemoveWorkspaceMembersRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkRemoveWorkspaceMembersResponse as BulkRemoveWorkspaceMembersResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkUnassignKeysRequest as BulkUnassignKeysRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkUnassignKeysResponse as BulkUnassignKeysResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkUnassignMembersRequest as BulkUnassignMembersRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkUnassignMembersResponse as BulkUnassignMembersResponse
from pyfect.ai.openrouter.generated._schemas_0 import BYOKProviderSlug as BYOKProviderSlug
from pyfect.ai.openrouter.generated._schemas_0 import ChatAssistantImages as ChatAssistantImages
from pyfect.ai.openrouter.generated._schemas_0 import ChatAudioOutput as ChatAudioOutput
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentAudio as ChatContentAudio
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentFile as ChatContentFile
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentImage as ChatContentImage
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentVideoInput as ChatContentVideoInput
from pyfect.ai.openrouter.generated._schemas_0 import ChatDebugOptions as ChatDebugOptions
from pyfect.ai.openrouter.generated._schemas_0 import ChatFinishReasonEnum as ChatFinishReasonEnum
from pyfect.ai.openrouter.generated._schemas_0 import ChatFormatGrammarConfig as ChatFormatGrammarConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatFormatJsonObjectConfig as ChatFormatJsonObjectConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatFormatPythonConfig as ChatFormatPythonConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatFormatTextConfig as ChatFormatTextConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatJsonSchemaConfig as ChatJsonSchemaConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatNamedToolChoice as ChatNamedToolChoice
from pyfect.ai.openrouter.generated._schemas_0 import ChatReasoningSummaryVerbosityEnum as ChatReasoningSummaryVerbosityEnum
from pyfect.ai.openrouter.generated._schemas_0 import ChatServerToolChoice as ChatServerToolChoice
from pyfect.ai.openrouter.generated._schemas_0 import Objects_6 as Objects_6
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamToolCall as ChatStreamToolCall
from pyfect.ai.openrouter.generated._schemas_0 import ChatTokenLogprob as ChatTokenLogprob
from pyfect.ai.openrouter.generated._schemas_0 import ChatToolCall as ChatToolCall
from pyfect.ai.openrouter.generated._schemas_0 import Union_ as Union_
from pyfect.ai.openrouter.generated._schemas_0 import Union_1 as Union_1
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterServerTool as CodeInterpreterServerTool
from pyfect.ai.openrouter.generated._schemas_0 import CodexLocalShellTool as CodexLocalShellTool
from pyfect.ai.openrouter.generated._schemas_0 import CompactionItem as CompactionItem
from pyfect.ai.openrouter.generated._schemas_0 import CompoundFilter as CompoundFilter
from pyfect.ai.openrouter.generated._schemas_0 import ComputerUseServerTool as ComputerUseServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ConflictResponseErrorData as ConflictResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ContainerAutoEnvironment as ContainerAutoEnvironment
from pyfect.ai.openrouter.generated._schemas_0 import ContainerReferenceEnvironment as ContainerReferenceEnvironment
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterAction as ContentFilterAction
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterBuiltinAction as ContentFilterBuiltinAction
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterBuiltinSlug as ContentFilterBuiltinSlug
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartAudio as ContentPartAudio
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartImage as ContentPartImage
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartVideo as ContentPartVideo
from pyfect.ai.openrouter.generated._schemas_0 import ContextCompactionItem as ContextCompactionItem
from pyfect.ai.openrouter.generated._schemas_0 import ContextCompressionEngine as ContextCompressionEngine
from pyfect.ai.openrouter.generated._schemas_0 import Objects_8 as Objects_8
from pyfect.ai.openrouter.generated._schemas_0 import CreateWorkspaceRequest as CreateWorkspaceRequest
from pyfect.ai.openrouter.generated._schemas_0 import CustomTool as CustomTool
from pyfect.ai.openrouter.generated._schemas_0 import CustomToolCallInputDeltaEvent as CustomToolCallInputDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import CustomToolCallInputDoneEvent as CustomToolCallInputDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import CustomToolCallItem as CustomToolCallItem
from pyfect.ai.openrouter.generated._schemas_0 import DABenchmarkEntry as DABenchmarkEntry
from pyfect.ai.openrouter.generated._schemas_0 import DatetimeServerToolConfig as DatetimeServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import DebugEvent as DebugEvent
from pyfect.ai.openrouter.generated._schemas_0 import DefaultParameters as DefaultParameters
from pyfect.ai.openrouter.generated._schemas_0 import DeleteBYOKKeyResponse as DeleteBYOKKeyResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteGuardrailResponse as DeleteGuardrailResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteObservabilityDestinationResponse as DeleteObservabilityDestinationResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteWorkspaceBudgetResponse as DeleteWorkspaceBudgetResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteWorkspaceResponse as DeleteWorkspaceResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeprecatedRoute as DeprecatedRoute
from pyfect.ai.openrouter.generated._schemas_0 import EdgeNetworkTimeoutResponseErrorData as EdgeNetworkTimeoutResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import EndpointInfo as EndpointInfo
from pyfect.ai.openrouter.generated._schemas_0 import EndpointStatus as EndpointStatus
from pyfect.ai.openrouter.generated._schemas_0 import EnumCapability as EnumCapability
from pyfect.ai.openrouter.generated._schemas_0 import ErrorEvent as ErrorEvent
from pyfect.ai.openrouter.generated._schemas_0 import FileCitation as FileCitation
from pyfect.ai.openrouter.generated._schemas_0 import FileDeleteResponse as FileDeleteResponse
from pyfect.ai.openrouter.generated._schemas_0 import FileMetadata as FileMetadata
from pyfect.ai.openrouter.generated._schemas_0 import FilePath as FilePath
from pyfect.ai.openrouter.generated._schemas_0 import FilesServerToolConfig as FilesServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ForbiddenResponseErrorData as ForbiddenResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import FormatJsonObjectConfig as FormatJsonObjectConfig
from pyfect.ai.openrouter.generated._schemas_0 import FormatJsonSchemaConfig as FormatJsonSchemaConfig
from pyfect.ai.openrouter.generated._schemas_0 import FormatTextConfig as FormatTextConfig
from pyfect.ai.openrouter.generated._schemas_0 import FrameImage as FrameImage
from pyfect.ai.openrouter.generated._schemas_0 import FunctionCallArgsDeltaEvent as FunctionCallArgsDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import FunctionCallArgsDoneEvent as FunctionCallArgsDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import FunctionTool as FunctionTool
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_1 as Arrays_1
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_2 as Arrays_2
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_3 as Arrays_3
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_4 as Arrays_4
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_5 as Arrays_5
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallAnalysisInProgressEvent as FusionCallAnalysisInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallCompletedEvent as FusionCallCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallInProgressEvent as FusionCallInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallPanelAddedEvent as FusionCallPanelAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallPanelCompletedEvent as FusionCallPanelCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallPanelDeltaEvent as FusionCallPanelDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallPanelFailedEvent as FusionCallPanelFailedEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallPanelReasoningDeltaEvent as FusionCallPanelReasoningDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionPlugin as FusionPlugin
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_6 as Arrays_6
from pyfect.ai.openrouter.generated._schemas_0 import Objects_9 as Objects_9
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_7 as Arrays_7
from pyfect.ai.openrouter.generated._schemas_0 import FusionSource as FusionSource
from pyfect.ai.openrouter.generated._schemas_0 import GenerationContentData as GenerationContentData
from pyfect.ai.openrouter.generated._schemas_0 import GoneResponseErrorData as GoneResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import GuardrailInterval as GuardrailInterval
from pyfect.ai.openrouter.generated._schemas_0 import ImageConfig as ImageConfig
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenCallCompletedEvent as ImageGenCallCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenCallGeneratingEvent as ImageGenCallGeneratingEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenCallInProgressEvent as ImageGenCallInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenCallPartialImageEvent as ImageGenCallPartialImageEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationServerTool as ImageGenerationServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationServerToolConfig as ImageGenerationServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationStatus as ImageGenerationStatus
from pyfect.ai.openrouter.generated._schemas_0 import Union_6 as Union_6
from pyfect.ai.openrouter.generated._schemas_0 import Union_8 as Union_8
from pyfect.ai.openrouter.generated._schemas_0 import Union_9 as Union_9
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenPartialImageEvent as ImageGenPartialImageEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenStreamErrorEvent as ImageGenStreamErrorEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenTextChunkEvent as ImageGenTextChunkEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageInputModality as ImageInputModality
from pyfect.ai.openrouter.generated._schemas_0 import ImageOutputModality as ImageOutputModality
from pyfect.ai.openrouter.generated._schemas_0 import ImagePricingEntry as ImagePricingEntry
from pyfect.ai.openrouter.generated._schemas_0 import IncompleteDetails as IncompleteDetails
from pyfect.ai.openrouter.generated._schemas_0 import InputAudio as InputAudio
from pyfect.ai.openrouter.generated._schemas_0 import InputFile as InputFile
from pyfect.ai.openrouter.generated._schemas_0 import InputImage as InputImage
from pyfect.ai.openrouter.generated._schemas_0 import InputModality as InputModality
from pyfect.ai.openrouter.generated._schemas_0 import InputVideo as InputVideo
from pyfect.ai.openrouter.generated._schemas_0 import InstructType as InstructType
from pyfect.ai.openrouter.generated._schemas_0 import InternalServerResponseErrorData as InternalServerResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ItemReferenceItem as ItemReferenceItem
from pyfect.ai.openrouter.generated._schemas_0 import KeyAssignment as KeyAssignment
from pyfect.ai.openrouter.generated._schemas_0 import Legacy_ChatContentVideoInput as Legacy_ChatContentVideoInput
from pyfect.ai.openrouter.generated._schemas_0 import McpApprovalRequestItem as McpApprovalRequestItem
from pyfect.ai.openrouter.generated._schemas_0 import McpApprovalResponseItem as McpApprovalResponseItem
from pyfect.ai.openrouter.generated._schemas_0 import McpCallItem as McpCallItem
from pyfect.ai.openrouter.generated._schemas_0 import McpListToolsItem as McpListToolsItem
from pyfect.ai.openrouter.generated._schemas_0 import McpServerTool as McpServerTool
from pyfect.ai.openrouter.generated._schemas_0 import MemberAssignment as MemberAssignment
from pyfect.ai.openrouter.generated._schemas_0 import MessagesAdvisorToolResultBlock as MessagesAdvisorToolResultBlock
from pyfect.ai.openrouter.generated._schemas_0 import MessagesContentBlockStopEvent as MessagesContentBlockStopEvent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesFallbackParam as MessagesFallbackParam
from pyfect.ai.openrouter.generated._schemas_0 import Union_10 as Union_10
from pyfect.ai.openrouter.generated._schemas_0 import Union_11 as Union_11
from pyfect.ai.openrouter.generated._schemas_0 import MessagesPingEvent as MessagesPingEvent
from pyfect.ai.openrouter.generated._schemas_0 import MetadataLevel as MetadataLevel
from pyfect.ai.openrouter.generated._schemas_0 import ModelGroup as ModelGroup
from pyfect.ai.openrouter.generated._schemas_0 import ModelLinks as ModelLinks
from pyfect.ai.openrouter.generated._schemas_0 import ModelName as ModelName
from pyfect.ai.openrouter.generated._schemas_0 import ModelsCountResponse as ModelsCountResponse
from pyfect.ai.openrouter.generated._schemas_0 import ModerationPlugin as ModerationPlugin
from pyfect.ai.openrouter.generated._schemas_0 import MultimodalMedia as MultimodalMedia
from pyfect.ai.openrouter.generated._schemas_0 import NamespaceFunctionTool as NamespaceFunctionTool
from pyfect.ai.openrouter.generated._schemas_0 import NotFoundResponseErrorData as NotFoundResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityFilterRuleGroup as ObservabilityFilterRuleGroup
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponseCustomToolCall as OpenAIResponseCustomToolCall
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesImageGenCallCompleted as OpenAIResponsesImageGenCallCompleted
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesImageGenCallGenerating as OpenAIResponsesImageGenCallGenerating
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesImageGenCallInProgress as OpenAIResponsesImageGenCallInProgress
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesImageGenCallPartialImage as OpenAIResponsesImageGenCallPartialImage
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesRefusalContent as OpenAIResponsesRefusalContent
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesResponseStatus as OpenAIResponsesResponseStatus
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesSearchCompleted as OpenAIResponsesSearchCompleted
from pyfect.ai.openrouter.generated._schemas_0 import Objects_11 as Objects_11
from pyfect.ai.openrouter.generated._schemas_0 import Objects_12 as Objects_12
from pyfect.ai.openrouter.generated._schemas_0 import Objects_13 as Objects_13
from pyfect.ai.openrouter.generated._schemas_0 import Objects_14 as Objects_14
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesTruncation as OpenAIResponsesTruncation
from pyfect.ai.openrouter.generated._schemas_0 import Objects_15 as Objects_15
from pyfect.ai.openrouter.generated._schemas_0 import Objects_16 as Objects_16
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesWebSearchCallInProgress as OpenAIResponsesWebSearchCallInProgress
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesWebSearchCallSearching as OpenAIResponsesWebSearchCallSearching
from pyfect.ai.openrouter.generated._schemas_0 import OpenResponsesTopLogprobs as OpenResponsesTopLogprobs
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicStopReason as ORAnthropicStopReason
from pyfect.ai.openrouter.generated._schemas_0 import OutputComputerCallItem as OutputComputerCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputCustomToolCallItem as OutputCustomToolCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputFunctionCallItem as OutputFunctionCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemCustomToolCall as OutputItemCustomToolCall
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemFunctionCall as OutputItemFunctionCall
from pyfect.ai.openrouter.generated._schemas_0 import OutputModality as OutputModality
from pyfect.ai.openrouter.generated._schemas_0 import OutputModalityEnum as OutputModalityEnum
from pyfect.ai.openrouter.generated._schemas_0 import Parameter as Parameter
from pyfect.ai.openrouter.generated._schemas_0 import ParetoRouterPlugin as ParetoRouterPlugin
from pyfect.ai.openrouter.generated._schemas_0 import PayloadTooLargeResponseErrorData as PayloadTooLargeResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import PaymentRequiredResponseErrorData as PaymentRequiredResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import PDFParserEngine as PDFParserEngine
from pyfect.ai.openrouter.generated._schemas_0 import PercentileLatencyCutoffs as PercentileLatencyCutoffs
from pyfect.ai.openrouter.generated._schemas_0 import PercentileStats as PercentileStats
from pyfect.ai.openrouter.generated._schemas_0 import PercentileThroughputCutoffs as PercentileThroughputCutoffs
from pyfect.ai.openrouter.generated._schemas_0 import PerRequestLimits as PerRequestLimits
from pyfect.ai.openrouter.generated._schemas_0 import PipelineStageType as PipelineStageType
from pyfect.ai.openrouter.generated._schemas_0 import PredictionContentText as PredictionContentText
from pyfect.ai.openrouter.generated._schemas_0 import PresetDesignatedVersion as PresetDesignatedVersion
from pyfect.ai.openrouter.generated._schemas_0 import PresetStatus as PresetStatus
from pyfect.ai.openrouter.generated._schemas_0 import Objects_18 as Objects_18
from pyfect.ai.openrouter.generated._schemas_0 import PricingOverride as PricingOverride
from pyfect.ai.openrouter.generated._schemas_0 import Objects_19 as Objects_19
from pyfect.ai.openrouter.generated._schemas_0 import Objects_20 as Objects_20
from pyfect.ai.openrouter.generated._schemas_0 import PromptInjectionScanScope as PromptInjectionScanScope
from pyfect.ai.openrouter.generated._schemas_0 import ProviderName as ProviderName
from pyfect.ai.openrouter.generated._schemas_0 import Objects_21 as Objects_21
from pyfect.ai.openrouter.generated._schemas_0 import Objects_22 as Objects_22
from pyfect.ai.openrouter.generated._schemas_0 import Objects_23 as Objects_23
from pyfect.ai.openrouter.generated._schemas_0 import Objects_24 as Objects_24
from pyfect.ai.openrouter.generated._schemas_0 import Objects_25 as Objects_25
from pyfect.ai.openrouter.generated._schemas_0 import Objects_26 as Objects_26
from pyfect.ai.openrouter.generated._schemas_0 import Objects_27 as Objects_27
from pyfect.ai.openrouter.generated._schemas_0 import Objects_28 as Objects_28
from pyfect.ai.openrouter.generated._schemas_0 import Objects_29 as Objects_29
from pyfect.ai.openrouter.generated._schemas_0 import Objects_30 as Objects_30
from pyfect.ai.openrouter.generated._schemas_0 import Objects_31 as Objects_31
from pyfect.ai.openrouter.generated._schemas_0 import Objects_32 as Objects_32
from pyfect.ai.openrouter.generated._schemas_0 import Objects_33 as Objects_33
from pyfect.ai.openrouter.generated._schemas_0 import Objects_34 as Objects_34
from pyfect.ai.openrouter.generated._schemas_0 import Objects_35 as Objects_35
from pyfect.ai.openrouter.generated._schemas_0 import Objects_36 as Objects_36
from pyfect.ai.openrouter.generated._schemas_0 import Objects_37 as Objects_37
from pyfect.ai.openrouter.generated._schemas_0 import Objects_38 as Objects_38
from pyfect.ai.openrouter.generated._schemas_0 import Objects_39 as Objects_39
from pyfect.ai.openrouter.generated._schemas_0 import Objects_40 as Objects_40
from pyfect.ai.openrouter.generated._schemas_0 import Objects_41 as Objects_41
from pyfect.ai.openrouter.generated._schemas_0 import Objects_42 as Objects_42
from pyfect.ai.openrouter.generated._schemas_0 import Objects_43 as Objects_43
from pyfect.ai.openrouter.generated._schemas_0 import Objects_44 as Objects_44
from pyfect.ai.openrouter.generated._schemas_0 import Objects_45 as Objects_45
from pyfect.ai.openrouter.generated._schemas_0 import Objects_46 as Objects_46
from pyfect.ai.openrouter.generated._schemas_0 import Objects_47 as Objects_47
from pyfect.ai.openrouter.generated._schemas_0 import Objects_48 as Objects_48
from pyfect.ai.openrouter.generated._schemas_0 import Objects_49 as Objects_49
from pyfect.ai.openrouter.generated._schemas_0 import Objects_50 as Objects_50
from pyfect.ai.openrouter.generated._schemas_0 import Objects_51 as Objects_51
from pyfect.ai.openrouter.generated._schemas_0 import Objects_52 as Objects_52
from pyfect.ai.openrouter.generated._schemas_0 import Objects_53 as Objects_53
from pyfect.ai.openrouter.generated._schemas_0 import Objects_54 as Objects_54
from pyfect.ai.openrouter.generated._schemas_0 import Objects_55 as Objects_55
from pyfect.ai.openrouter.generated._schemas_0 import Objects_56 as Objects_56
from pyfect.ai.openrouter.generated._schemas_0 import Objects_57 as Objects_57
from pyfect.ai.openrouter.generated._schemas_0 import Objects_58 as Objects_58
from pyfect.ai.openrouter.generated._schemas_0 import Objects_59 as Objects_59
from pyfect.ai.openrouter.generated._schemas_0 import Objects_60 as Objects_60
from pyfect.ai.openrouter.generated._schemas_0 import Objects_61 as Objects_61
from pyfect.ai.openrouter.generated._schemas_0 import Objects_62 as Objects_62
from pyfect.ai.openrouter.generated._schemas_0 import Objects_63 as Objects_63
from pyfect.ai.openrouter.generated._schemas_0 import Objects_64 as Objects_64
from pyfect.ai.openrouter.generated._schemas_0 import Objects_65 as Objects_65
from pyfect.ai.openrouter.generated._schemas_0 import Objects_66 as Objects_66
from pyfect.ai.openrouter.generated._schemas_0 import Objects_67 as Objects_67
from pyfect.ai.openrouter.generated._schemas_0 import Objects_68 as Objects_68
from pyfect.ai.openrouter.generated._schemas_0 import Objects_69 as Objects_69
from pyfect.ai.openrouter.generated._schemas_0 import Objects_70 as Objects_70
from pyfect.ai.openrouter.generated._schemas_0 import Objects_71 as Objects_71
from pyfect.ai.openrouter.generated._schemas_0 import Objects_72 as Objects_72
from pyfect.ai.openrouter.generated._schemas_0 import Objects_73 as Objects_73
from pyfect.ai.openrouter.generated._schemas_0 import Objects_74 as Objects_74
from pyfect.ai.openrouter.generated._schemas_0 import Objects_75 as Objects_75
from pyfect.ai.openrouter.generated._schemas_0 import Objects_76 as Objects_76
from pyfect.ai.openrouter.generated._schemas_0 import Objects_77 as Objects_77
from pyfect.ai.openrouter.generated._schemas_0 import Objects_78 as Objects_78
from pyfect.ai.openrouter.generated._schemas_0 import Objects_79 as Objects_79
from pyfect.ai.openrouter.generated._schemas_0 import Objects_80 as Objects_80
from pyfect.ai.openrouter.generated._schemas_0 import Objects_81 as Objects_81
from pyfect.ai.openrouter.generated._schemas_0 import Objects_82 as Objects_82
from pyfect.ai.openrouter.generated._schemas_0 import Objects_83 as Objects_83
from pyfect.ai.openrouter.generated._schemas_0 import Objects_84 as Objects_84
from pyfect.ai.openrouter.generated._schemas_0 import Objects_85 as Objects_85
from pyfect.ai.openrouter.generated._schemas_0 import Objects_86 as Objects_86
from pyfect.ai.openrouter.generated._schemas_0 import Objects_87 as Objects_87
from pyfect.ai.openrouter.generated._schemas_0 import Objects_88 as Objects_88
from pyfect.ai.openrouter.generated._schemas_0 import Objects_89 as Objects_89
from pyfect.ai.openrouter.generated._schemas_0 import Objects_90 as Objects_90
from pyfect.ai.openrouter.generated._schemas_0 import Objects_91 as Objects_91
from pyfect.ai.openrouter.generated._schemas_0 import Objects_92 as Objects_92
from pyfect.ai.openrouter.generated._schemas_0 import Objects_93 as Objects_93
from pyfect.ai.openrouter.generated._schemas_0 import Objects_94 as Objects_94
from pyfect.ai.openrouter.generated._schemas_0 import Objects_95 as Objects_95
from pyfect.ai.openrouter.generated._schemas_0 import Objects_96 as Objects_96
from pyfect.ai.openrouter.generated._schemas_0 import Objects_97 as Objects_97
from pyfect.ai.openrouter.generated._schemas_0 import Objects_98 as Objects_98
from pyfect.ai.openrouter.generated._schemas_0 import Objects_99 as Objects_99
from pyfect.ai.openrouter.generated._schemas_0 import Objects_100 as Objects_100
from pyfect.ai.openrouter.generated._schemas_0 import Objects_101 as Objects_101
from pyfect.ai.openrouter.generated._schemas_0 import Objects_102 as Objects_102
from pyfect.ai.openrouter.generated._schemas_0 import Objects_103 as Objects_103
from pyfect.ai.openrouter.generated._schemas_0 import Objects_104 as Objects_104
from pyfect.ai.openrouter.generated._schemas_0 import Objects_105 as Objects_105
from pyfect.ai.openrouter.generated._schemas_0 import Objects_106 as Objects_106
from pyfect.ai.openrouter.generated._schemas_0 import Objects_107 as Objects_107
from pyfect.ai.openrouter.generated._schemas_0 import Objects_108 as Objects_108
from pyfect.ai.openrouter.generated._schemas_0 import Objects_109 as Objects_109
from pyfect.ai.openrouter.generated._schemas_0 import Objects_110 as Objects_110
from pyfect.ai.openrouter.generated._schemas_0 import Objects_111 as Objects_111
from pyfect.ai.openrouter.generated._schemas_0 import Objects_112 as Objects_112
from pyfect.ai.openrouter.generated._schemas_0 import Objects_113 as Objects_113
from pyfect.ai.openrouter.generated._schemas_0 import Objects_114 as Objects_114
from pyfect.ai.openrouter.generated._schemas_0 import Objects_115 as Objects_115
from pyfect.ai.openrouter.generated._schemas_0 import Objects_116 as Objects_116
from pyfect.ai.openrouter.generated._schemas_0 import Objects_117 as Objects_117
from pyfect.ai.openrouter.generated._schemas_0 import Objects_118 as Objects_118
from pyfect.ai.openrouter.generated._schemas_0 import Objects_119 as Objects_119
from pyfect.ai.openrouter.generated._schemas_0 import Objects_120 as Objects_120
from pyfect.ai.openrouter.generated._schemas_0 import Objects_121 as Objects_121
from pyfect.ai.openrouter.generated._schemas_0 import Objects_122 as Objects_122
from pyfect.ai.openrouter.generated._schemas_0 import Objects_123 as Objects_123
from pyfect.ai.openrouter.generated._schemas_0 import Objects_124 as Objects_124
from pyfect.ai.openrouter.generated._schemas_0 import Objects_125 as Objects_125
from pyfect.ai.openrouter.generated._schemas_0 import Objects_126 as Objects_126
from pyfect.ai.openrouter.generated._schemas_0 import Objects_127 as Objects_127
from pyfect.ai.openrouter.generated._schemas_0 import Objects_128 as Objects_128
from pyfect.ai.openrouter.generated._schemas_0 import Objects_129 as Objects_129
from pyfect.ai.openrouter.generated._schemas_0 import Objects_130 as Objects_130
from pyfect.ai.openrouter.generated._schemas_0 import Objects_131 as Objects_131
from pyfect.ai.openrouter.generated._schemas_0 import Objects_132 as Objects_132
from pyfect.ai.openrouter.generated._schemas_0 import Objects_133 as Objects_133
from pyfect.ai.openrouter.generated._schemas_0 import Objects_134 as Objects_134
from pyfect.ai.openrouter.generated._schemas_0 import Objects_135 as Objects_135
from pyfect.ai.openrouter.generated._schemas_0 import Objects_136 as Objects_136
from pyfect.ai.openrouter.generated._schemas_0 import Objects_137 as Objects_137
from pyfect.ai.openrouter.generated._schemas_0 import Objects_138 as Objects_138
from pyfect.ai.openrouter.generated._schemas_0 import Objects_139 as Objects_139
from pyfect.ai.openrouter.generated._schemas_0 import Objects_140 as Objects_140
from pyfect.ai.openrouter.generated._schemas_0 import Objects_141 as Objects_141
from pyfect.ai.openrouter.generated._schemas_0 import Objects_142 as Objects_142
from pyfect.ai.openrouter.generated._schemas_0 import Objects_143 as Objects_143
from pyfect.ai.openrouter.generated._schemas_0 import Objects_144 as Objects_144
from pyfect.ai.openrouter.generated._schemas_0 import Objects_145 as Objects_145
from pyfect.ai.openrouter.generated._schemas_0 import Objects_146 as Objects_146
from pyfect.ai.openrouter.generated._schemas_0 import Objects_147 as Objects_147
from pyfect.ai.openrouter.generated._schemas_0 import ProviderOverloadedResponseErrorData as ProviderOverloadedResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ProviderResponse as ProviderResponse
from pyfect.ai.openrouter.generated._schemas_0 import ProviderSort as ProviderSort
from pyfect.ai.openrouter.generated._schemas_0 import ProviderSortConfig as ProviderSortConfig
from pyfect.ai.openrouter.generated._schemas_0 import Quantization as Quantization
from pyfect.ai.openrouter.generated._schemas_0 import RangeCapability as RangeCapability
from pyfect.ai.openrouter.generated._schemas_0 import RankingsDailyItem as RankingsDailyItem
from pyfect.ai.openrouter.generated._schemas_0 import RankingsDailyMeta as RankingsDailyMeta
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningContext as ReasoningContext
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDeltaEvent as ReasoningDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDoneEvent as ReasoningDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningEffort as ReasoningEffort
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningFormat as ReasoningFormat
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningMode as ReasoningMode
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryText as ReasoningSummaryText
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryTextDeltaEvent as ReasoningSummaryTextDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryTextDoneEvent as ReasoningSummaryTextDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryVerbosity as ReasoningSummaryVerbosity
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningTextContent as ReasoningTextContent
from pyfect.ai.openrouter.generated._schemas_0 import RefusalDeltaEvent as RefusalDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import RefusalDoneEvent as RefusalDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import Objects_149 as Objects_149
from pyfect.ai.openrouter.generated._schemas_0 import RequestTimeoutResponseErrorData as RequestTimeoutResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ResponseHealingPlugin as ResponseHealingPlugin
from pyfect.ai.openrouter.generated._schemas_0 import ResponseIncludesEnum as ResponseIncludesEnum
from pyfect.ai.openrouter.generated._schemas_0 import ResponsesErrorField as ResponsesErrorField
from pyfect.ai.openrouter.generated._schemas_0 import RouterAttempt as RouterAttempt
from pyfect.ai.openrouter.generated._schemas_0 import RouterParams as RouterParams
from pyfect.ai.openrouter.generated._schemas_0 import RoutingStrategy as RoutingStrategy
from pyfect.ai.openrouter.generated._schemas_0 import SandboxSleepAfterSeconds as SandboxSleepAfterSeconds
from pyfect.ai.openrouter.generated._schemas_0 import SearchContextSizeEnum as SearchContextSizeEnum
from pyfect.ai.openrouter.generated._schemas_0 import SearchModelsServerToolConfig as SearchModelsServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import SearchQualityLevel as SearchQualityLevel
from pyfect.ai.openrouter.generated._schemas_0 import Objects_150 as Objects_150
from pyfect.ai.openrouter.generated._schemas_0 import ServiceTier as ServiceTier
from pyfect.ai.openrouter.generated._schemas_0 import ServiceUnavailableResponseErrorData as ServiceUnavailableResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ShellCallStatus as ShellCallStatus
from pyfect.ai.openrouter.generated._schemas_0 import ShellServerTool as ShellServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ShellServerToolEngine as ShellServerToolEngine
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenFinishReasonIs as StopServerToolsWhenFinishReasonIs
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenHasToolCall as StopServerToolsWhenHasToolCall
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenMaxCost as StopServerToolsWhenMaxCost
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenMaxTokensUsed as StopServerToolsWhenMaxTokensUsed
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenStepCountIs as StopServerToolsWhenStepCountIs
from pyfect.ai.openrouter.generated._schemas_0 import StreamLogprob as StreamLogprob
from pyfect.ai.openrouter.generated._schemas_0 import StreamLogprobTopLogprob as StreamLogprobTopLogprob
from pyfect.ai.openrouter.generated._schemas_0 import STTInputAudio as STTInputAudio
from pyfect.ai.openrouter.generated._schemas_0 import STTSegment as STTSegment
from pyfect.ai.openrouter.generated._schemas_0 import STTTimestampGranularity as STTTimestampGranularity
from pyfect.ai.openrouter.generated._schemas_0 import STTUsage as STTUsage
from pyfect.ai.openrouter.generated._schemas_0 import STTWord as STTWord
from pyfect.ai.openrouter.generated._schemas_0 import SubagentNestedTool as SubagentNestedTool
from pyfect.ai.openrouter.generated._schemas_0 import SubagentReasoning as SubagentReasoning
from pyfect.ai.openrouter.generated._schemas_0 import SubmitGenerationFeedbackRequest as SubmitGenerationFeedbackRequest
from pyfect.ai.openrouter.generated._schemas_0 import SubmitGenerationFeedbackResponse as SubmitGenerationFeedbackResponse
from pyfect.ai.openrouter.generated._schemas_0 import SupportedParameters as SupportedParameters
from pyfect.ai.openrouter.generated._schemas_0 import TaskClassificationMacroCategory as TaskClassificationMacroCategory
from pyfect.ai.openrouter.generated._schemas_0 import TaskClassificationModel as TaskClassificationModel
from pyfect.ai.openrouter.generated._schemas_0 import TextDeltaEvent as TextDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import TextDoneEvent as TextDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import ToolCallStatus as ToolCallStatus
from pyfect.ai.openrouter.generated._schemas_0 import ToolChoiceAllowed as ToolChoiceAllowed
from pyfect.ai.openrouter.generated._schemas_0 import TooManyRequestsResponseErrorData as TooManyRequestsResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import TopProviderInfo as TopProviderInfo
from pyfect.ai.openrouter.generated._schemas_0 import TraceConfig as TraceConfig
from pyfect.ai.openrouter.generated._schemas_0 import Truncation as Truncation
from pyfect.ai.openrouter.generated._schemas_0 import UnauthorizedResponseErrorData as UnauthorizedResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarkPricing as UnifiedBenchmarkPricing
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksMeta as UnifiedBenchmarksMeta
from pyfect.ai.openrouter.generated._schemas_0 import UnprocessableEntityResponseErrorData as UnprocessableEntityResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKeyRequest as UpdateBYOKKeyRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpdateWorkspaceRequest as UpdateWorkspaceRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpsertWorkspaceBudgetRequest as UpsertWorkspaceBudgetRequest
from pyfect.ai.openrouter.generated._schemas_0 import URLCitation as URLCitation
from pyfect.ai.openrouter.generated._schemas_0 import VideoGenerationUsage as VideoGenerationUsage
from pyfect.ai.openrouter.generated._schemas_0 import VideoModel as VideoModel
from pyfect.ai.openrouter.generated._schemas_0 import WebFetchEngineEnum as WebFetchEngineEnum
from pyfect.ai.openrouter.generated._schemas_0 import WebFetchPlugin as WebFetchPlugin
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_13 as Arrays_13
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_14 as Arrays_14
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchCallCompletedEvent as WebSearchCallCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchCallInProgressEvent as WebSearchCallInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchCallSearchingEvent as WebSearchCallSearchingEvent
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_15 as Arrays_15
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_16 as Arrays_16
from pyfect.ai.openrouter.generated._schemas_0 import Objects_152 as Objects_152
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchEngine as WebSearchEngine
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchEngineEnum as WebSearchEngineEnum
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_17 as Arrays_17
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_18 as Arrays_18
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchSource as WebSearchSource
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchStatus as WebSearchStatus
from pyfect.ai.openrouter.generated._schemas_0 import Objects_153 as Objects_153
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchUserLocationServerTool as WebSearchUserLocationServerTool
from pyfect.ai.openrouter.generated._schemas_0 import Workspace as Workspace
from pyfect.ai.openrouter.generated._schemas_0 import WorkspaceBudget as WorkspaceBudget
from pyfect.ai.openrouter.generated._schemas_0 import WorkspaceBudgetInterval as WorkspaceBudgetInterval
from pyfect.ai.openrouter.generated._schemas_0 import WorkspaceMember as WorkspaceMember
from pyfect.ai.openrouter.generated._schemas_0 import ActivityResponse as ActivityResponse
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_ as Arrays_
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBashCodeExecutionResult as AnthropicBashCodeExecutionResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCacheControlDirective as AnthropicCacheControlDirective
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentCacheControl as ChatContentCacheControl
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCacheCreation as AnthropicCacheCreation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationsConfig as AnthropicCitationsConfig
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextCitation as AnthropicTextCitation
from pyfect.ai.openrouter.generated._schemas_0 import MessagesContentBlockDeltaEvent as MessagesContentBlockDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecutionResult as AnthropicCodeExecutionResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicEncryptedCodeExecutionResult as AnthropicEncryptedCodeExecutionResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCaller as AnthropicCaller
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicNullableCaller as ORAnthropicNullableCaller
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBase64ImageSource as AnthropicBase64ImageSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicInputTokensClearAtLeast as AnthropicInputTokensClearAtLeast
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicIterationCacheCreation as AnthropicIterationCacheCreation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecutionToolResultError as AnthropicCodeExecutionToolResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchResultError as AnthropicToolSearchResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionContent as AnthropicTextEditorCodeExecutionContent
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchResult as AnthropicToolSearchResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebSearchToolUserLocation as AnthropicWebSearchToolUserLocation
from pyfect.ai.openrouter.generated._schemas_0 import MessagesErrorDetail as MessagesErrorDetail
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchServerToolConfig as ApplyPatchServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallOperation as ApplyPatchCallOperation
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemApplyPatchCall as OutputItemApplyPatchCall
from pyfect.ai.openrouter.generated._schemas_0 import BadGatewayResponse as BadGatewayResponse
from pyfect.ai.openrouter.generated._schemas_0 import BadRequestResponse as BadRequestResponse
from pyfect.ai.openrouter.generated._schemas_0 import BYOKKey as BYOKKey
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKeyRequest as CreateBYOKKeyRequest
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentVideo as ChatContentVideo
from pyfect.ai.openrouter.generated._schemas_0 import ChatFormatJsonSchemaConfig as ChatFormatJsonSchemaConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatToolChoice as ChatToolChoice
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamOptions as ChatStreamOptions
from pyfect.ai.openrouter.generated._schemas_0 import Objects_7 as Objects_7
from pyfect.ai.openrouter.generated._schemas_0 import FileSearchServerTool as FileSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ConflictResponse as ConflictResponse
from pyfect.ai.openrouter.generated._schemas_0 import BashServerToolEnvironment as BashServerToolEnvironment
from pyfect.ai.openrouter.generated._schemas_0 import ShellServerToolEnvironment as ShellServerToolEnvironment
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterEntry as ContentFilterEntry
from pyfect.ai.openrouter.generated._schemas_0 import InputReference as InputReference
from pyfect.ai.openrouter.generated._schemas_0 import ContextCompressionPlugin as ContextCompressionPlugin
from pyfect.ai.openrouter.generated._schemas_0 import CostDetails as CostDetails
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_9 as Arrays_9
from pyfect.ai.openrouter.generated._schemas_0 import DatetimeServerTool as DatetimeServerTool
from pyfect.ai.openrouter.generated._schemas_0 import EdgeNetworkTimeoutResponse as EdgeNetworkTimeoutResponse
from pyfect.ai.openrouter.generated._schemas_0 import EndpointsMetadata as EndpointsMetadata
from pyfect.ai.openrouter.generated._schemas_0 import FileListResponse as FileListResponse
from pyfect.ai.openrouter.generated._schemas_0 import FilesServerTool as FilesServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ForbiddenResponse as ForbiddenResponse
from pyfect.ai.openrouter.generated._schemas_0 import Formats as Formats
from pyfect.ai.openrouter.generated._schemas_0 import FusionAnalysisResult as FusionAnalysisResult
from pyfect.ai.openrouter.generated._schemas_0 import GenerationContentResponse as GenerationContentResponse
from pyfect.ai.openrouter.generated._schemas_0 import GoneResponse as GoneResponse
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationServerTool_OpenRouter as ImageGenerationServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import OutputImageGenerationCallItem as OutputImageGenerationCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemImageGenerationCall as OutputItemImageGenerationCall
from pyfect.ai.openrouter.generated._schemas_0 import ImageModelArchitecture as ImageModelArchitecture
from pyfect.ai.openrouter.generated._schemas_0 import InternalServerResponse as InternalServerResponse
from pyfect.ai.openrouter.generated._schemas_0 import ListKeyAssignmentsResponse as ListKeyAssignmentsResponse
from pyfect.ai.openrouter.generated._schemas_0 import Legacy_ChatContentVideo as Legacy_ChatContentVideo
from pyfect.ai.openrouter.generated._schemas_0 import ListMemberAssignmentsResponse as ListMemberAssignmentsResponse
from pyfect.ai.openrouter.generated._schemas_0 import MessagesOutputConfig as MessagesOutputConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatModelNames as ChatModelNames
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartInputAudio as ContentPartInputAudio
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartInputFile as ContentPartInputFile
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartInputVideo as ContentPartInputVideo
from pyfect.ai.openrouter.generated._schemas_0 import NamespaceTool as NamespaceTool
from pyfect.ai.openrouter.generated._schemas_0 import NotFoundResponse as NotFoundResponse
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityFilterRulesConfig as ObservabilityFilterRulesConfig
from pyfect.ai.openrouter.generated._schemas_0 import Objects_10 as Objects_10
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesUsage as OpenAIResponsesUsage
from pyfect.ai.openrouter.generated._schemas_0 import OpenResponsesLogProbs as OpenResponsesLogProbs
from pyfect.ai.openrouter.generated._schemas_0 import ModelArchitecture as ModelArchitecture
from pyfect.ai.openrouter.generated._schemas_0 import PayloadTooLargeResponse as PayloadTooLargeResponse
from pyfect.ai.openrouter.generated._schemas_0 import PaymentRequiredResponse as PaymentRequiredResponse
from pyfect.ai.openrouter.generated._schemas_0 import PDFParserOptions as PDFParserOptions
from pyfect.ai.openrouter.generated._schemas_0 import PreferredMaxLatency as PreferredMaxLatency
from pyfect.ai.openrouter.generated._schemas_0 import PreferredMinThroughput as PreferredMinThroughput
from pyfect.ai.openrouter.generated._schemas_0 import PipelineStage as PipelineStage
from pyfect.ai.openrouter.generated._schemas_0 import Objects_17 as Objects_17
from pyfect.ai.openrouter.generated._schemas_0 import GetPresetVersionResponse as GetPresetVersionResponse
from pyfect.ai.openrouter.generated._schemas_0 import ListPresetVersionsResponse as ListPresetVersionsResponse
from pyfect.ai.openrouter.generated._schemas_0 import Preset as Preset
from pyfect.ai.openrouter.generated._schemas_0 import PresetWithDesignatedVersion as PresetWithDesignatedVersion
from pyfect.ai.openrouter.generated._schemas_0 import Preview_WebSearchUserLocation as Preview_WebSearchUserLocation
from pyfect.ai.openrouter.generated._schemas_0 import PublicPricing as PublicPricing
from pyfect.ai.openrouter.generated._schemas_0 import PromptCacheBreakpoint as PromptCacheBreakpoint
from pyfect.ai.openrouter.generated._schemas_0 import PromptCacheOptions as PromptCacheOptions
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterBuiltinEntry as ContentFilterBuiltinEntry
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterBuiltinEntryInput as ContentFilterBuiltinEntryInput
from pyfect.ai.openrouter.generated._schemas_0 import Union_2 as Union_2
from pyfect.ai.openrouter.generated._schemas_0 import Union_3 as Union_3
from pyfect.ai.openrouter.generated._schemas_0 import Union_4 as Union_4
from pyfect.ai.openrouter.generated._schemas_0 import ProviderOptions as ProviderOptions
from pyfect.ai.openrouter.generated._schemas_0 import ProviderOverloadedResponse as ProviderOverloadedResponse
from pyfect.ai.openrouter.generated._schemas_0 import GenerationResponse as GenerationResponse
from pyfect.ai.openrouter.generated._schemas_0 import Union_5 as Union_5
from pyfect.ai.openrouter.generated._schemas_0 import PublicEndpoint as PublicEndpoint
from pyfect.ai.openrouter.generated._schemas_0 import CapabilityDescriptor as CapabilityDescriptor
from pyfect.ai.openrouter.generated._schemas_0 import AppRankingsResponse as AppRankingsResponse
from pyfect.ai.openrouter.generated._schemas_0 import RankingsDailyResponse as RankingsDailyResponse
from pyfect.ai.openrouter.generated._schemas_0 import Union_12 as Union_12
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDetailEncrypted as ReasoningDetailEncrypted
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDetailServerToolCall as ReasoningDetailServerToolCall
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDetailSummary as ReasoningDetailSummary
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDetailText as ReasoningDetailText
from pyfect.ai.openrouter.generated._schemas_0 import BaseReasoningSummaryPartAddedEvent as BaseReasoningSummaryPartAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseReasoningSummaryPartDoneEvent as BaseReasoningSummaryPartDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import OutputReasoningItem as OutputReasoningItem
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningItem as ReasoningItem
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryPartAddedEvent as ReasoningSummaryPartAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryPartDoneEvent as ReasoningSummaryPartDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import Objects_5 as Objects_5
from pyfect.ai.openrouter.generated._schemas_0 import Union_13 as Union_13
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemReasoning as OutputItemReasoning
from pyfect.ai.openrouter.generated._schemas_0 import RequestMetadata as RequestMetadata
from pyfect.ai.openrouter.generated._schemas_0 import RequestTimeoutResponse as RequestTimeoutResponse
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_10 as Arrays_10
from pyfect.ai.openrouter.generated._schemas_0 import ChatSearchModelsServerTool as ChatSearchModelsServerTool
from pyfect.ai.openrouter.generated._schemas_0 import MessagesSearchModelsServerTool as MessagesSearchModelsServerTool
from pyfect.ai.openrouter.generated._schemas_0 import SearchModelsServerTool_OpenRouter as SearchModelsServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import ServerToolUseDetails as ServerToolUseDetails
from pyfect.ai.openrouter.generated._schemas_0 import ServiceUnavailableResponse as ServiceUnavailableResponse
from pyfect.ai.openrouter.generated._schemas_0 import OutputShellCallItem as OutputShellCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputShellCallOutputItem as OutputShellCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenCondition as StopServerToolsWhenCondition
from pyfect.ai.openrouter.generated._schemas_0 import STTResponse as STTResponse
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_12 as Arrays_12
from pyfect.ai.openrouter.generated._schemas_0 import ImageEndpoint as ImageEndpoint
from pyfect.ai.openrouter.generated._schemas_0 import TaskClassificationItem as TaskClassificationItem
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterCallItem as CodeInterpreterCallItem
from pyfect.ai.openrouter.generated._schemas_0 import FunctionCallItem as FunctionCallItem
from pyfect.ai.openrouter.generated._schemas_0 import LocalShellCallItem as LocalShellCallItem
from pyfect.ai.openrouter.generated._schemas_0 import LocalShellCallOutputItem as LocalShellCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponseFunctionToolCall as OpenAIResponseFunctionToolCall
from pyfect.ai.openrouter.generated._schemas_0 import OutputAdvisorServerToolItem as OutputAdvisorServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputBashServerToolItem as OutputBashServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputBrowserUseServerToolItem as OutputBrowserUseServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputCodeInterpreterCallItem as OutputCodeInterpreterCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputCodeInterpreterServerToolItem as OutputCodeInterpreterServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputDatetimeItem as OutputDatetimeItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputFileSearchServerToolItem as OutputFileSearchServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputFilesServerToolItem as OutputFilesServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputImageGenerationServerToolItem as OutputImageGenerationServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputMcpServerToolItem as OutputMcpServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputMemoryServerToolItem as OutputMemoryServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputSearchModelsServerToolItem as OutputSearchModelsServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputSubagentServerToolItem as OutputSubagentServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputTextEditorServerToolItem as OutputTextEditorServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputToolSearchServerToolItem as OutputToolSearchServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputWebFetchServerToolItem as OutputWebFetchServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputWebSearchServerToolItem as OutputWebSearchServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import ShellCallItem as ShellCallItem
from pyfect.ai.openrouter.generated._schemas_0 import ShellCallOutputItem as ShellCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesToolChoice as OpenAIResponsesToolChoice
from pyfect.ai.openrouter.generated._schemas_0 import TooManyRequestsResponse as TooManyRequestsResponse
from pyfect.ai.openrouter.generated._schemas_0 import UnauthorizedResponse as UnauthorizedResponse
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksAAItem as UnifiedBenchmarksAAItem
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksDAItem as UnifiedBenchmarksDAItem
from pyfect.ai.openrouter.generated._schemas_0 import UnprocessableEntityResponse as UnprocessableEntityResponse
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesAnnotation as OpenAIResponsesAnnotation
from pyfect.ai.openrouter.generated._schemas_0 import VideoGenerationResponse as VideoGenerationResponse
from pyfect.ai.openrouter.generated._schemas_0 import VideoModelsListResponse as VideoModelsListResponse
from pyfect.ai.openrouter.generated._schemas_0 import WebFetchServerToolConfig as WebFetchServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchDomainFilter as WebSearchDomainFilter
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchPlugin as WebSearchPlugin
from pyfect.ai.openrouter.generated._schemas_0 import OutputFileSearchCallItem as OutputFileSearchCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemFileSearchCall as OutputItemFileSearchCall
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemWebSearchCall as OutputItemWebSearchCall
from pyfect.ai.openrouter.generated._schemas_0 import OutputWebSearchCallItem as OutputWebSearchCallItem
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchUserLocation as WebSearchUserLocation
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchConfig as WebSearchConfig
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchServerToolConfig as WebSearchServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import CreateWorkspaceResponse as CreateWorkspaceResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetWorkspaceResponse as GetWorkspaceResponse
from pyfect.ai.openrouter.generated._schemas_0 import ListWorkspacesResponse as ListWorkspacesResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateWorkspaceResponse as UpdateWorkspaceResponse
from pyfect.ai.openrouter.generated._schemas_0 import ListWorkspaceBudgetsResponse as ListWorkspaceBudgetsResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpsertWorkspaceBudgetResponse as UpsertWorkspaceBudgetResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkAddWorkspaceMembersResponse as BulkAddWorkspaceMembersResponse
from pyfect.ai.openrouter.generated._schemas_0 import ListWorkspaceMembersResponse as ListWorkspaceMembersResponse
from pyfect.ai.openrouter.generated._schemas_0 import AdvisorServerToolConfig as AdvisorServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBashCodeExecutionContent as AnthropicBashCodeExecutionContent
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextBlockParam as AnthropicTextBlockParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchToolBm25 as AnthropicToolSearchToolBm25
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchToolRegex as AnthropicToolSearchToolRegex
from pyfect.ai.openrouter.generated._schemas_0 import FusionServerToolConfig as FusionServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicUsage as AnthropicUsage
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicDocumentBlock as AnthropicDocumentBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextBlock as AnthropicTextBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolUseBlock as AnthropicToolUseBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebSearchToolResult as AnthropicWebSearchToolResult
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicServerToolUseBlock as ORAnthropicServerToolUseBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicImageBlockParam as AnthropicImageBlockParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicAdvisorMessageUsageIteration as AnthropicAdvisorMessageUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBaseUsageIteration as AnthropicBaseUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCompactionUsageIteration as AnthropicCompactionUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicMessageUsageIteration as AnthropicMessageUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicUnknownUsageIteration as AnthropicUnknownUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecutionContent as AnthropicCodeExecutionContent
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionToolResult as AnthropicTextEditorCodeExecutionToolResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchContent as AnthropicToolSearchContent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesErrorResponse as MessagesErrorResponse
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchServerTool_OpenRouter as ApplyPatchServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallItem as ApplyPatchCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputApplyPatchCallItem as OutputApplyPatchCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputApplyPatchServerToolItem as OutputApplyPatchServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKeyResponse as CreateBYOKKeyResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetBYOKKeyResponse as GetBYOKKeyResponse
from pyfect.ai.openrouter.generated._schemas_0 import ListBYOKKeysResponse as ListBYOKKeysResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKeyResponse as UpdateBYOKKeyResponse
from pyfect.ai.openrouter.generated._schemas_0 import ChatTokenLogprobs as ChatTokenLogprobs
from pyfect.ai.openrouter.generated._schemas_0 import BashServerToolConfig as BashServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ShellServerToolConfig as ShellServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ModelBenchmarks as ModelBenchmarks
from pyfect.ai.openrouter.generated._schemas_0 import TextConfig as TextConfig
from pyfect.ai.openrouter.generated._schemas_0 import TextExtendedConfig as TextExtendedConfig
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallAnalysisCompletedEvent as FusionCallAnalysisCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import OutputFusionServerToolItem as OutputFusionServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import ImageModelListItem as ImageModelListItem
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityArizeDestination as ObservabilityArizeDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityBraintrustDestination as ObservabilityBraintrustDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityClickhouseDestination as ObservabilityClickhouseDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityDatadogDestination as ObservabilityDatadogDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityGrafanaDestination as ObservabilityGrafanaDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityLangfuseDestination as ObservabilityLangfuseDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityLangsmithDestination as ObservabilityLangsmithDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityNewrelicDestination as ObservabilityNewrelicDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityOpikDestination as ObservabilityOpikDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityOtelCollectorDestination as ObservabilityOtelCollectorDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityPosthogDestination as ObservabilityPosthogDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityRampDestination as ObservabilityRampDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityS3Destination as ObservabilityS3Destination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilitySentryDestination as ObservabilitySentryDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilitySnowflakeDestination as ObservabilitySnowflakeDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityWeaveDestination as ObservabilityWeaveDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityWebhookDestination as ObservabilityWebhookDestination
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityFilterRulesConfigNullable as ObservabilityFilterRulesConfigNullable
from pyfect.ai.openrouter.generated._schemas_0 import BaseTextDeltaEvent as BaseTextDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseTextDoneEvent as BaseTextDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import FileParserPlugin as FileParserPlugin
from pyfect.ai.openrouter.generated._schemas_0 import Objects_148 as Objects_148
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_11 as Arrays_11
from pyfect.ai.openrouter.generated._schemas_0 import Prediction as Prediction
from pyfect.ai.openrouter.generated._schemas_0 import ListPresetsResponse as ListPresetsResponse
from pyfect.ai.openrouter.generated._schemas_0 import CreatePresetFromInferenceResponse as CreatePresetFromInferenceResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetPresetResponse as GetPresetResponse
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentText as ChatContentText
from pyfect.ai.openrouter.generated._schemas_0 import CustomToolCallOutputItem as CustomToolCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import FunctionCallOutputItem as FunctionCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import InputText as InputText
from pyfect.ai.openrouter.generated._schemas_0 import Guardrail as Guardrail
from pyfect.ai.openrouter.generated._schemas_0 import CreateGuardrailRequest as CreateGuardrailRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpdateGuardrailRequest as UpdateGuardrailRequest
from pyfect.ai.openrouter.generated._schemas_0 import SpeechRequest as SpeechRequest
from pyfect.ai.openrouter.generated._schemas_0 import STTRequest as STTRequest
from pyfect.ai.openrouter.generated._schemas_0 import VideoGenerationRequest as VideoGenerationRequest
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationProviderPreferences as ImageGenerationProviderPreferences
from pyfect.ai.openrouter.generated._schemas_0 import ListEndpointsResponse as ListEndpointsResponse
from pyfect.ai.openrouter.generated._schemas_0 import ModelReasoning as ModelReasoning
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDetailUnion as ReasoningDetailUnion
from pyfect.ai.openrouter.generated._schemas_0 import BaseReasoningConfig as BaseReasoningConfig
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningConfig as ReasoningConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatUsage as ChatUsage
from pyfect.ai.openrouter.generated._schemas_0 import Usage as Usage
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhen as StopServerToolsWhen
from pyfect.ai.openrouter.generated._schemas_0 import SubagentServerToolConfig as SubagentServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ImageModelEndpointsResponse as ImageModelEndpointsResponse
from pyfect.ai.openrouter.generated._schemas_0 import TaskClassificationResponse as TaskClassificationResponse
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksResponse as UnifiedBenchmarksResponse
from pyfect.ai.openrouter.generated._schemas_0 import AnnotationAddedEvent as AnnotationAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseAnnotationAddedEvent as BaseAnnotationAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import ResponseOutputText as ResponseOutputText
from pyfect.ai.openrouter.generated._schemas_0 import WebFetchServerTool as WebFetchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import Preview_20250311_WebSearchServerTool as Preview_20250311_WebSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import Preview_WebSearchServerTool as Preview_WebSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import Legacy_WebSearchServerTool as Legacy_WebSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchServerTool as WebSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ChatWebSearchShorthand as ChatWebSearchShorthand
from pyfect.ai.openrouter.generated._schemas_0 import OpenRouterWebSearchServerTool as OpenRouterWebSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchServerTool_OpenRouter as WebSearchServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import AdvisorServerTool_OpenRouter as AdvisorServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBashCodeExecutionToolResult as AnthropicBashCodeExecutionToolResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicSearchResultBlockParam as AnthropicSearchResultBlockParam
from pyfect.ai.openrouter.generated._schemas_0 import FusionServerTool_OpenRouter as FusionServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebFetchBlock as AnthropicWebFetchBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicDocumentBlockParam as AnthropicDocumentBlockParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicUsageIteration as AnthropicUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecutionToolResult as AnthropicCodeExecutionToolResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchToolResult as AnthropicToolSearchToolResult
from pyfect.ai.openrouter.generated._schemas_0 import BashServerTool as BashServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ShellServerTool_OpenRouter as ShellServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import ImageModelsListResponse as ImageModelsListResponse
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityDestination as ObservabilityDestination
from pyfect.ai.openrouter.generated._schemas_0 import CreateObservabilityDestinationRequest as CreateObservabilityDestinationRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpdateObservabilityDestinationRequest as UpdateObservabilityDestinationRequest
from pyfect.ai.openrouter.generated._schemas_0 import ProviderPreferences as ProviderPreferences
from pyfect.ai.openrouter.generated._schemas_0 import OpenRouterMetadata as OpenRouterMetadata
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentItems as ChatContentItems
from pyfect.ai.openrouter.generated._schemas_0 import ChatDeveloperMessage as ChatDeveloperMessage
from pyfect.ai.openrouter.generated._schemas_0 import ChatSystemMessage as ChatSystemMessage
from pyfect.ai.openrouter.generated._schemas_0 import AgentMessageItem as AgentMessageItem
from pyfect.ai.openrouter.generated._schemas_0 import EasyInputMessage as EasyInputMessage
from pyfect.ai.openrouter.generated._schemas_0 import InputMessageItem as InputMessageItem
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponseCustomToolCallOutput as OpenAIResponseCustomToolCallOutput
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponseFunctionToolCallOutput as OpenAIResponseFunctionToolCallOutput
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponseInputMessageItem as OpenAIResponseInputMessageItem
from pyfect.ai.openrouter.generated._schemas_0 import Objects_151 as Objects_151
from pyfect.ai.openrouter.generated._schemas_0 import CreateGuardrailResponse as CreateGuardrailResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetGuardrailResponse as GetGuardrailResponse
from pyfect.ai.openrouter.generated._schemas_0 import ListGuardrailsResponse as ListGuardrailsResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateGuardrailResponse as UpdateGuardrailResponse
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationRequest as ImageGenerationRequest
from pyfect.ai.openrouter.generated._schemas_0 import Model as Model
from pyfect.ai.openrouter.generated._schemas_0 import ChatReasoningDetails as ChatReasoningDetails
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamReasoningDetails as ChatStreamReasoningDetails
from pyfect.ai.openrouter.generated._schemas_0 import SubagentServerTool_OpenRouter as SubagentServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import BaseContentPartAddedEvent as BaseContentPartAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import BaseContentPartDoneEvent as BaseContentPartDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartAddedEvent as ContentPartAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartDoneEvent as ContentPartDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import OutputMessage as OutputMessage
from pyfect.ai.openrouter.generated._schemas_0 import OutputMessageItem as OutputMessageItem
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebFetchContent as AnthropicWebFetchContent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesMessageParam as MessagesMessageParam
from pyfect.ai.openrouter.generated._schemas_0 import Union_7 as Union_7
from pyfect.ai.openrouter.generated._schemas_0 import MessagesDeltaEvent as MessagesDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import CreateObservabilityDestinationResponse as CreateObservabilityDestinationResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetObservabilityDestinationResponse as GetObservabilityDestinationResponse
from pyfect.ai.openrouter.generated._schemas_0 import ListObservabilityDestinationsResponse as ListObservabilityDestinationsResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateObservabilityDestinationResponse as UpdateObservabilityDestinationResponse
from pyfect.ai.openrouter.generated._schemas_0 import MessagesErrorEvent as MessagesErrorEvent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesStopEvent as MessagesStopEvent
from pyfect.ai.openrouter.generated._schemas_0 import ChatToolMessage as ChatToolMessage
from pyfect.ai.openrouter.generated._schemas_0 import ChatUserMessage as ChatUserMessage
from pyfect.ai.openrouter.generated._schemas_0 import StoredPromptTemplate as StoredPromptTemplate
from pyfect.ai.openrouter.generated._schemas_0 import ModelResponse as ModelResponse
from pyfect.ai.openrouter.generated._schemas_0 import ModelsListResponseData as ModelsListResponseData
from pyfect.ai.openrouter.generated._schemas_0 import ChatAssistantMessage as ChatAssistantMessage
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamDelta as ChatStreamDelta
from pyfect.ai.openrouter.generated._schemas_0 import AdditionalToolsItem as AdditionalToolsItem
from pyfect.ai.openrouter.generated._schemas_0 import ChatFunctionTool as ChatFunctionTool
from pyfect.ai.openrouter.generated._schemas_0 import BaseInputs as BaseInputs
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemAddedEvent as OutputItemAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemDoneEvent as OutputItemDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import OutputItems as OutputItems
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebFetchToolResult as AnthropicWebFetchToolResult
from pyfect.ai.openrouter.generated._schemas_0 import MessagesRequest as MessagesRequest
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationUsage as ImageGenerationUsage
from pyfect.ai.openrouter.generated._schemas_0 import ModelsListResponse as ModelsListResponse
from pyfect.ai.openrouter.generated._schemas_0 import ChatChoice as ChatChoice
from pyfect.ai.openrouter.generated._schemas_0 import ChatMessages as ChatMessages
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamChoice as ChatStreamChoice
from pyfect.ai.openrouter.generated._schemas_0 import Arrays_8 as Arrays_8
from pyfect.ai.openrouter.generated._schemas_0 import BaseResponsesResult as BaseResponsesResult
from pyfect.ai.openrouter.generated._schemas_0 import OpenResponsesResult as OpenResponsesResult
from pyfect.ai.openrouter.generated._schemas_0 import StreamEventsResponseOutputItemAdded as StreamEventsResponseOutputItemAdded
from pyfect.ai.openrouter.generated._schemas_0 import StreamEventsResponseOutputItemDone as StreamEventsResponseOutputItemDone
from pyfect.ai.openrouter.generated._schemas_0 import MessagesContentBlockStartEvent as MessagesContentBlockStartEvent
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicContentBlock as ORAnthropicContentBlock
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenCompletedEvent as ImageGenCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationResponse as ImageGenerationResponse
from pyfect.ai.openrouter.generated._schemas_0 import ChatResult as ChatResult
from pyfect.ai.openrouter.generated._schemas_0 import ChatRequest as ChatRequest
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamChunk as ChatStreamChunk
from pyfect.ai.openrouter.generated._schemas_0 import Inputs as Inputs
from pyfect.ai.openrouter.generated._schemas_0 import CompletedEvent as CompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import CreatedEvent as CreatedEvent
from pyfect.ai.openrouter.generated._schemas_0 import FailedEvent as FailedEvent
from pyfect.ai.openrouter.generated._schemas_0 import IncompleteEvent as IncompleteEvent
from pyfect.ai.openrouter.generated._schemas_0 import InProgressEvent as InProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import OpenResponsesCreatedEvent as OpenResponsesCreatedEvent
from pyfect.ai.openrouter.generated._schemas_0 import OpenResponsesInProgressEvent as OpenResponsesInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import StreamEventsResponseCompleted as StreamEventsResponseCompleted
from pyfect.ai.openrouter.generated._schemas_0 import StreamEventsResponseFailed as StreamEventsResponseFailed
from pyfect.ai.openrouter.generated._schemas_0 import StreamEventsResponseIncomplete as StreamEventsResponseIncomplete
from pyfect.ai.openrouter.generated._schemas_0 import BaseMessagesResult as BaseMessagesResult
from pyfect.ai.openrouter.generated._schemas_0 import MessagesResult as MessagesResult
from pyfect.ai.openrouter.generated._schemas_0 import MessagesStartEvent as MessagesStartEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageStreamingResponse as ImageStreamingResponse
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamingResponse as ChatStreamingResponse
from pyfect.ai.openrouter.generated._schemas_0 import ResponsesRequest as ResponsesRequest
from pyfect.ai.openrouter.generated._schemas_0 import StreamEvents as StreamEvents
from pyfect.ai.openrouter.generated._schemas_0 import MessagesStreamEvents as MessagesStreamEvents
from pyfect.ai.openrouter.generated._schemas_0 import ResponsesStreamingResponse as ResponsesStreamingResponse
from pyfect.ai.openrouter.generated._schemas_0 import MessagesStreamingResponse as MessagesStreamingResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivityParams as GetUserActivityParams
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity200 as GetUserActivity200
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity400 as GetUserActivity400
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity401 as GetUserActivity401
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity403 as GetUserActivity403
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity404 as GetUserActivity404
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity500 as GetUserActivity500
from pyfect.ai.openrouter.generated._schemas_0 import GetAnalyticsMetaParams as GetAnalyticsMetaParams
from pyfect.ai.openrouter.generated._schemas_0 import GetAnalyticsMeta200 as GetAnalyticsMeta200
from pyfect.ai.openrouter.generated._schemas_0 import GetAnalyticsMeta401 as GetAnalyticsMeta401
from pyfect.ai.openrouter.generated._schemas_0 import GetAnalyticsMeta403 as GetAnalyticsMeta403
from pyfect.ai.openrouter.generated._schemas_0 import GetAnalyticsMeta500 as GetAnalyticsMeta500
from pyfect.ai.openrouter.generated._schemas_0 import QueryAnalyticsParams as QueryAnalyticsParams
from pyfect.ai.openrouter.generated._schemas_0 import QueryAnalyticsRequestJson as QueryAnalyticsRequestJson
from pyfect.ai.openrouter.generated._schemas_0 import QueryAnalytics200 as QueryAnalytics200
from pyfect.ai.openrouter.generated._schemas_0 import QueryAnalytics400 as QueryAnalytics400
from pyfect.ai.openrouter.generated._schemas_0 import QueryAnalytics401 as QueryAnalytics401
from pyfect.ai.openrouter.generated._schemas_0 import QueryAnalytics403 as QueryAnalytics403
from pyfect.ai.openrouter.generated._schemas_0 import QueryAnalytics408 as QueryAnalytics408
from pyfect.ai.openrouter.generated._schemas_0 import QueryAnalytics500 as QueryAnalytics500
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeechParams as CreateAudioSpeechParams
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeechRequestJson as CreateAudioSpeechRequestJson
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeech400 as CreateAudioSpeech400
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeech401 as CreateAudioSpeech401
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeech402 as CreateAudioSpeech402
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeech404 as CreateAudioSpeech404
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeech429 as CreateAudioSpeech429
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeech500 as CreateAudioSpeech500
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeech502 as CreateAudioSpeech502
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeech503 as CreateAudioSpeech503
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeech524 as CreateAudioSpeech524
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioSpeech529 as CreateAudioSpeech529
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptionsParams as CreateAudioTranscriptionsParams
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptionsRequestJson as CreateAudioTranscriptionsRequestJson
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions200 as CreateAudioTranscriptions200
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions400 as CreateAudioTranscriptions400
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions401 as CreateAudioTranscriptions401
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions402 as CreateAudioTranscriptions402
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions404 as CreateAudioTranscriptions404
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions429 as CreateAudioTranscriptions429
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions500 as CreateAudioTranscriptions500
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions502 as CreateAudioTranscriptions502
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions503 as CreateAudioTranscriptions503
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions524 as CreateAudioTranscriptions524
from pyfect.ai.openrouter.generated._schemas_0 import CreateAudioTranscriptions529 as CreateAudioTranscriptions529
from pyfect.ai.openrouter.generated._schemas_0 import ExchangeAuthCodeForAPIKeyParams as ExchangeAuthCodeForAPIKeyParams
from pyfect.ai.openrouter.generated._schemas_0 import ExchangeAuthCodeForAPIKeyRequestJson as ExchangeAuthCodeForAPIKeyRequestJson
from pyfect.ai.openrouter.generated._schemas_0 import ExchangeAuthCodeForAPIKey200 as ExchangeAuthCodeForAPIKey200
from pyfect.ai.openrouter.generated._schemas_0 import ExchangeAuthCodeForAPIKey400 as ExchangeAuthCodeForAPIKey400
from pyfect.ai.openrouter.generated._schemas_0 import ExchangeAuthCodeForAPIKey403 as ExchangeAuthCodeForAPIKey403
from pyfect.ai.openrouter.generated._schemas_0 import ExchangeAuthCodeForAPIKey500 as ExchangeAuthCodeForAPIKey500
from pyfect.ai.openrouter.generated._schemas_0 import CreateAuthKeysCodeParams as CreateAuthKeysCodeParams
from pyfect.ai.openrouter.generated._schemas_0 import CreateAuthKeysCodeRequestJson as CreateAuthKeysCodeRequestJson
from pyfect.ai.openrouter.generated._schemas_0 import CreateAuthKeysCode200 as CreateAuthKeysCode200
from pyfect.ai.openrouter.generated._schemas_0 import CreateAuthKeysCode400 as CreateAuthKeysCode400
from pyfect.ai.openrouter.generated._schemas_0 import CreateAuthKeysCode401 as CreateAuthKeysCode401
from pyfect.ai.openrouter.generated._schemas_0 import CreateAuthKeysCode403 as CreateAuthKeysCode403
from pyfect.ai.openrouter.generated._schemas_0 import CreateAuthKeysCode409 as CreateAuthKeysCode409
from pyfect.ai.openrouter.generated._schemas_0 import CreateAuthKeysCode500 as CreateAuthKeysCode500
from pyfect.ai.openrouter.generated._schemas_0 import GetBenchmarksParams as GetBenchmarksParams
from pyfect.ai.openrouter.generated._schemas_0 import GetBenchmarks200 as GetBenchmarks200
from pyfect.ai.openrouter.generated._schemas_0 import GetBenchmarks400 as GetBenchmarks400
from pyfect.ai.openrouter.generated._schemas_0 import GetBenchmarks401 as GetBenchmarks401
from pyfect.ai.openrouter.generated._schemas_0 import GetBenchmarks429 as GetBenchmarks429
from pyfect.ai.openrouter.generated._schemas_0 import GetBenchmarks500 as GetBenchmarks500
from pyfect.ai.openrouter.generated._schemas_0 import ListBYOKKeysParams as ListBYOKKeysParams
from pyfect.ai.openrouter.generated._schemas_0 import ListBYOKKeys200 as ListBYOKKeys200
from pyfect.ai.openrouter.generated._schemas_0 import ListBYOKKeys400 as ListBYOKKeys400
from pyfect.ai.openrouter.generated._schemas_0 import ListBYOKKeys401 as ListBYOKKeys401
from pyfect.ai.openrouter.generated._schemas_0 import ListBYOKKeys500 as ListBYOKKeys500
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKeyParams as CreateBYOKKeyParams
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKeyRequestJson as CreateBYOKKeyRequestJson
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKey201 as CreateBYOKKey201
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKey400 as CreateBYOKKey400
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKey401 as CreateBYOKKey401
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKey403 as CreateBYOKKey403
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKey500 as CreateBYOKKey500
from pyfect.ai.openrouter.generated._schemas_0 import GetBYOKKeyParams as GetBYOKKeyParams
from pyfect.ai.openrouter.generated._schemas_0 import GetBYOKKey200 as GetBYOKKey200
from pyfect.ai.openrouter.generated._schemas_0 import GetBYOKKey401 as GetBYOKKey401
from pyfect.ai.openrouter.generated._schemas_0 import GetBYOKKey404 as GetBYOKKey404
from pyfect.ai.openrouter.generated._schemas_0 import GetBYOKKey500 as GetBYOKKey500
from pyfect.ai.openrouter.generated._schemas_0 import DeleteBYOKKeyParams as DeleteBYOKKeyParams
from pyfect.ai.openrouter.generated._schemas_0 import DeleteBYOKKey200 as DeleteBYOKKey200
from pyfect.ai.openrouter.generated._schemas_0 import DeleteBYOKKey401 as DeleteBYOKKey401
from pyfect.ai.openrouter.generated._schemas_0 import DeleteBYOKKey404 as DeleteBYOKKey404
from pyfect.ai.openrouter.generated._schemas_0 import DeleteBYOKKey500 as DeleteBYOKKey500
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKeyParams as UpdateBYOKKeyParams
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKeyRequestJson as UpdateBYOKKeyRequestJson
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKey200 as UpdateBYOKKey200
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKey400 as UpdateBYOKKey400
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKey401 as UpdateBYOKKey401
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKey404 as UpdateBYOKKey404
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKey500 as UpdateBYOKKey500
from pyfect.ai.openrouter.generated._schemas_0 import SendChatCompletionRequestParams as SendChatCompletionRequestParams
from pyfect.ai.openrouter.generated._schemas_0 import SendChatCompletionRequestRequestJson as SendChatCompletionRequestRequestJson
from pyfect.ai.openrouter.generated._schemas_0 import SendChatCompletionRequest200 as SendChatCompletionRequest200
from pyfect.ai.openrouter.generated._schemas_0 import SendChatCompletionRequest200Sse as SendChatCompletionRequest200Sse
from pyfect.ai.openrouter.generated._schemas_0 import SendChatCompletionRequest400 as SendChatCompletionRequest400
from pyfect.ai.openrouter.generated._schemas_0 import SendChatCompletionRequest401 as SendChatCompletionRequest401
from pyfect.ai.openrouter.generated._schemas_0 import SendChatCompletionRequest402 as SendChatCompletionRequest402
from pyfect.ai.openrouter.generated._schemas_0 import SendChatCompletionRequest403 as SendChatCompletionRequest403
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest404 as SendChatCompletionRequest404
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest408 as SendChatCompletionRequest408
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest413 as SendChatCompletionRequest413
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest422 as SendChatCompletionRequest422
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest429 as SendChatCompletionRequest429
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest500 as SendChatCompletionRequest500
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest502 as SendChatCompletionRequest502
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest503 as SendChatCompletionRequest503
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest524 as SendChatCompletionRequest524
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest529 as SendChatCompletionRequest529
from pyfect.ai.openrouter.generated._schemas_1 import GetTaskClassificationsParams as GetTaskClassificationsParams
from pyfect.ai.openrouter.generated._schemas_1 import GetTaskClassifications200 as GetTaskClassifications200
from pyfect.ai.openrouter.generated._schemas_1 import GetTaskClassifications400 as GetTaskClassifications400
from pyfect.ai.openrouter.generated._schemas_1 import GetTaskClassifications401 as GetTaskClassifications401
from pyfect.ai.openrouter.generated._schemas_1 import GetTaskClassifications429 as GetTaskClassifications429
from pyfect.ai.openrouter.generated._schemas_1 import GetTaskClassifications500 as GetTaskClassifications500
from pyfect.ai.openrouter.generated._schemas_1 import GetCreditsParams as GetCreditsParams
from pyfect.ai.openrouter.generated._schemas_1 import GetCredits200 as GetCredits200
from pyfect.ai.openrouter.generated._schemas_1 import GetCredits401 as GetCredits401
from pyfect.ai.openrouter.generated._schemas_1 import GetCredits403 as GetCredits403
from pyfect.ai.openrouter.generated._schemas_1 import GetCredits500 as GetCredits500
from pyfect.ai.openrouter.generated._schemas_1 import CreateCoinbaseChargeParams as CreateCoinbaseChargeParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateCoinbaseCharge410 as CreateCoinbaseCharge410
from pyfect.ai.openrouter.generated._schemas_1 import GetAppRankingsParams as GetAppRankingsParams
from pyfect.ai.openrouter.generated._schemas_1 import GetAppRankings200 as GetAppRankings200
from pyfect.ai.openrouter.generated._schemas_1 import GetAppRankings400 as GetAppRankings400
from pyfect.ai.openrouter.generated._schemas_1 import GetAppRankings401 as GetAppRankings401
from pyfect.ai.openrouter.generated._schemas_1 import GetAppRankings429 as GetAppRankings429
from pyfect.ai.openrouter.generated._schemas_1 import GetAppRankings500 as GetAppRankings500
from pyfect.ai.openrouter.generated._schemas_1 import GetRankingsDailyParams as GetRankingsDailyParams
from pyfect.ai.openrouter.generated._schemas_1 import GetRankingsDaily200 as GetRankingsDaily200
from pyfect.ai.openrouter.generated._schemas_1 import GetRankingsDaily400 as GetRankingsDaily400
from pyfect.ai.openrouter.generated._schemas_1 import GetRankingsDaily401 as GetRankingsDaily401
from pyfect.ai.openrouter.generated._schemas_1 import GetRankingsDaily429 as GetRankingsDaily429
from pyfect.ai.openrouter.generated._schemas_1 import GetRankingsDaily500 as GetRankingsDaily500
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddingsParams as CreateEmbeddingsParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddingsRequestJson as CreateEmbeddingsRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings200 as CreateEmbeddings200
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings200Sse as CreateEmbeddings200Sse
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings400 as CreateEmbeddings400
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings401 as CreateEmbeddings401
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings402 as CreateEmbeddings402
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings404 as CreateEmbeddings404
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings429 as CreateEmbeddings429
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings500 as CreateEmbeddings500
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings502 as CreateEmbeddings502
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings503 as CreateEmbeddings503
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings524 as CreateEmbeddings524
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings529 as CreateEmbeddings529
from pyfect.ai.openrouter.generated._schemas_1 import ListEmbeddingsModelsParams as ListEmbeddingsModelsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListEmbeddingsModels200 as ListEmbeddingsModels200
from pyfect.ai.openrouter.generated._schemas_1 import ListEmbeddingsModels400 as ListEmbeddingsModels400
from pyfect.ai.openrouter.generated._schemas_1 import ListEmbeddingsModels500 as ListEmbeddingsModels500
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpointsZdrParams as ListEndpointsZdrParams
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpointsZdr200 as ListEndpointsZdr200
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpointsZdr403 as ListEndpointsZdr403
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpointsZdr500 as ListEndpointsZdr500
from pyfect.ai.openrouter.generated._schemas_1 import ListFilesParams as ListFilesParams
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles200 as ListFiles200
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles400 as ListFiles400
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles401 as ListFiles401
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles429 as ListFiles429
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles500 as ListFiles500
from pyfect.ai.openrouter.generated._schemas_1 import UploadFileParams as UploadFileParams
from pyfect.ai.openrouter.generated._schemas_1 import UploadFileRequestFormData as UploadFileRequestFormData
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile200 as UploadFile200
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile400 as UploadFile400
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile401 as UploadFile401
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile403 as UploadFile403
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile413 as UploadFile413
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile429 as UploadFile429
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile500 as UploadFile500
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadataParams as GetFileMetadataParams
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata200 as GetFileMetadata200
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata401 as GetFileMetadata401
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata404 as GetFileMetadata404
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata429 as GetFileMetadata429
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata500 as GetFileMetadata500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFileParams as DeleteFileParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile200 as DeleteFile200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile401 as DeleteFile401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile404 as DeleteFile404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile429 as DeleteFile429
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile500 as DeleteFile500
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContentParams as DownloadFileContentParams
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent400 as DownloadFileContent400
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent401 as DownloadFileContent401
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent404 as DownloadFileContent404
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent429 as DownloadFileContent429
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent500 as DownloadFileContent500
from pyfect.ai.openrouter.generated._schemas_1 import GetGenerationParams as GetGenerationParams
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration200 as GetGeneration200
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration401 as GetGeneration401
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration402 as GetGeneration402
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration404 as GetGeneration404
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration429 as GetGeneration429
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration500 as GetGeneration500
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration502 as GetGeneration502
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration524 as GetGeneration524
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration529 as GetGeneration529
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContentParams as ListGenerationContentParams
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent200 as ListGenerationContent200
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent401 as ListGenerationContent401
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent403 as ListGenerationContent403
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent404 as ListGenerationContent404
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent429 as ListGenerationContent429
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent500 as ListGenerationContent500
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent502 as ListGenerationContent502
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent524 as ListGenerationContent524
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent529 as ListGenerationContent529
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedbackParams as SubmitGenerationFeedbackParams
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedbackRequestJson as SubmitGenerationFeedbackRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback200 as SubmitGenerationFeedback200
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback400 as SubmitGenerationFeedback400
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback401 as SubmitGenerationFeedback401
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback404 as SubmitGenerationFeedback404
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback429 as SubmitGenerationFeedback429
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback500 as SubmitGenerationFeedback500
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailsParams as ListGuardrailsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrails200 as ListGuardrails200
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrails400 as ListGuardrails400
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrails401 as ListGuardrails401
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrails500 as ListGuardrails500
from pyfect.ai.openrouter.generated._schemas_1 import CreateGuardrailParams as CreateGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateGuardrailRequestJson as CreateGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateGuardrail201 as CreateGuardrail201
from pyfect.ai.openrouter.generated._schemas_1 import CreateGuardrail400 as CreateGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import CreateGuardrail401 as CreateGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import CreateGuardrail403 as CreateGuardrail403
from pyfect.ai.openrouter.generated._schemas_1 import CreateGuardrail500 as CreateGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import GetGuardrailParams as GetGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import GetGuardrail200 as GetGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import GetGuardrail401 as GetGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import GetGuardrail404 as GetGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import GetGuardrail500 as GetGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrailParams as DeleteGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrail200 as DeleteGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrail401 as DeleteGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrail404 as DeleteGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrail500 as DeleteGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrailParams as UpdateGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrailRequestJson as UpdateGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail200 as UpdateGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail400 as UpdateGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail401 as UpdateGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail404 as UpdateGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail500 as UpdateGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignmentsParams as ListGuardrailKeyAssignmentsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignments200 as ListGuardrailKeyAssignments200
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignments401 as ListGuardrailKeyAssignments401
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignments404 as ListGuardrailKeyAssignments404
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignments500 as ListGuardrailKeyAssignments500
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrailParams as BulkAssignKeysToGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrailRequestJson as BulkAssignKeysToGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail200 as BulkAssignKeysToGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail400 as BulkAssignKeysToGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail401 as BulkAssignKeysToGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail404 as BulkAssignKeysToGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail500 as BulkAssignKeysToGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrailParams as BulkUnassignKeysFromGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrailRequestJson as BulkUnassignKeysFromGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail200 as BulkUnassignKeysFromGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail400 as BulkUnassignKeysFromGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail401 as BulkUnassignKeysFromGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail404 as BulkUnassignKeysFromGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail500 as BulkUnassignKeysFromGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignmentsParams as ListGuardrailMemberAssignmentsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignments200 as ListGuardrailMemberAssignments200
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignments401 as ListGuardrailMemberAssignments401
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignments404 as ListGuardrailMemberAssignments404
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignments500 as ListGuardrailMemberAssignments500
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrailParams as BulkAssignMembersToGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrailRequestJson as BulkAssignMembersToGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail200 as BulkAssignMembersToGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail400 as BulkAssignMembersToGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail401 as BulkAssignMembersToGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail404 as BulkAssignMembersToGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail500 as BulkAssignMembersToGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrailParams as BulkUnassignMembersFromGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrailRequestJson as BulkUnassignMembersFromGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail200 as BulkUnassignMembersFromGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail400 as BulkUnassignMembersFromGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail401 as BulkUnassignMembersFromGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail404 as BulkUnassignMembersFromGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail500 as BulkUnassignMembersFromGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignmentsParams as ListKeyAssignmentsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignments200 as ListKeyAssignments200
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignments401 as ListKeyAssignments401
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignments500 as ListKeyAssignments500
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignmentsParams as ListMemberAssignmentsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignments200 as ListMemberAssignments200
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignments401 as ListMemberAssignments401
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignments500 as ListMemberAssignments500
from pyfect.ai.openrouter.generated._schemas_1 import CreateImagesParams as CreateImagesParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateImagesRequestJson as CreateImagesRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages200 as CreateImages200
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages200Sse as CreateImages200Sse
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages400 as CreateImages400
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages401 as CreateImages401
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages402 as CreateImages402
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages403 as CreateImages403
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages404 as CreateImages404
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages413 as CreateImages413
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages429 as CreateImages429
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages500 as CreateImages500
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages502 as CreateImages502
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages524 as CreateImages524
from pyfect.ai.openrouter.generated._schemas_1 import CreateImages529 as CreateImages529
from pyfect.ai.openrouter.generated._schemas_1 import ListImageModelsParams as ListImageModelsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListImageModels200 as ListImageModels200
from pyfect.ai.openrouter.generated._schemas_1 import ListImageModels500 as ListImageModels500
from pyfect.ai.openrouter.generated._schemas_1 import ListImageModelEndpointsParams as ListImageModelEndpointsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListImageModelEndpoints200 as ListImageModelEndpoints200
from pyfect.ai.openrouter.generated._schemas_1 import ListImageModelEndpoints404 as ListImageModelEndpoints404
from pyfect.ai.openrouter.generated._schemas_1 import ListImageModelEndpoints500 as ListImageModelEndpoints500
from pyfect.ai.openrouter.generated._schemas_1 import GetCurrentKeyParams as GetCurrentKeyParams
from pyfect.ai.openrouter.generated._schemas_1 import GetCurrentKey200 as GetCurrentKey200
from pyfect.ai.openrouter.generated._schemas_1 import GetCurrentKey401 as GetCurrentKey401
from pyfect.ai.openrouter.generated._schemas_1 import GetCurrentKey500 as GetCurrentKey500
from pyfect.ai.openrouter.generated._schemas_1 import ListParams as ListParams
from pyfect.ai.openrouter.generated._schemas_1 import List200 as List200
from pyfect.ai.openrouter.generated._schemas_1 import List400 as List400
from pyfect.ai.openrouter.generated._schemas_1 import List401 as List401
from pyfect.ai.openrouter.generated._schemas_1 import List429 as List429
from pyfect.ai.openrouter.generated._schemas_1 import List500 as List500
from pyfect.ai.openrouter.generated._schemas_1 import CreateKeysParams as CreateKeysParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateKeysRequestJson as CreateKeysRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateKeys201 as CreateKeys201
from pyfect.ai.openrouter.generated._schemas_1 import CreateKeys400 as CreateKeys400
from pyfect.ai.openrouter.generated._schemas_1 import CreateKeys401 as CreateKeys401
from pyfect.ai.openrouter.generated._schemas_1 import CreateKeys403 as CreateKeys403
from pyfect.ai.openrouter.generated._schemas_1 import CreateKeys429 as CreateKeys429
from pyfect.ai.openrouter.generated._schemas_1 import CreateKeys500 as CreateKeys500
from pyfect.ai.openrouter.generated._schemas_1 import GetKeyParams as GetKeyParams
from pyfect.ai.openrouter.generated._schemas_1 import GetKey200 as GetKey200
from pyfect.ai.openrouter.generated._schemas_1 import GetKey401 as GetKey401
from pyfect.ai.openrouter.generated._schemas_1 import GetKey404 as GetKey404
from pyfect.ai.openrouter.generated._schemas_1 import GetKey429 as GetKey429
from pyfect.ai.openrouter.generated._schemas_1 import GetKey500 as GetKey500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeysParams as DeleteKeysParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys200 as DeleteKeys200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys401 as DeleteKeys401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys404 as DeleteKeys404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys429 as DeleteKeys429
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys500 as DeleteKeys500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeysParams as UpdateKeysParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeysRequestJson as UpdateKeysRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys200 as UpdateKeys200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys400 as UpdateKeys400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys401 as UpdateKeys401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys404 as UpdateKeys404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys429 as UpdateKeys429
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys500 as UpdateKeys500
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessagesParams as CreateMessagesParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessagesRequestJson as CreateMessagesRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessages200 as CreateMessages200
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessages200Sse as CreateMessages200Sse
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessages400 as CreateMessages400
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessages401 as CreateMessages401
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessages403 as CreateMessages403
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessages404 as CreateMessages404
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessages429 as CreateMessages429
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessages500 as CreateMessages500
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessages503 as CreateMessages503
from pyfect.ai.openrouter.generated._schemas_1 import CreateMessages529 as CreateMessages529
from pyfect.ai.openrouter.generated._schemas_1 import GetModelParams as GetModelParams
from pyfect.ai.openrouter.generated._schemas_1 import GetModel200 as GetModel200
from pyfect.ai.openrouter.generated._schemas_1 import GetModel403 as GetModel403
from pyfect.ai.openrouter.generated._schemas_1 import GetModel404 as GetModel404
from pyfect.ai.openrouter.generated._schemas_1 import GetModel500 as GetModel500
from pyfect.ai.openrouter.generated._schemas_1 import GetModelsParams as GetModelsParams
from pyfect.ai.openrouter.generated._schemas_1 import GetModels200 as GetModels200
from pyfect.ai.openrouter.generated._schemas_1 import GetModels400 as GetModels400
from pyfect.ai.openrouter.generated._schemas_1 import GetModels403 as GetModels403
from pyfect.ai.openrouter.generated._schemas_1 import GetModels500 as GetModels500
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpointsParams as ListEndpointsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpoints200 as ListEndpoints200
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpoints403 as ListEndpoints403
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpoints404 as ListEndpoints404
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpoints500 as ListEndpoints500
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsCountParams as ListModelsCountParams
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsCount200 as ListModelsCount200
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsCount400 as ListModelsCount400
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsCount403 as ListModelsCount403
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsCount500 as ListModelsCount500
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUserParams as ListModelsUserParams
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUser200 as ListModelsUser200
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUser401 as ListModelsUser401
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUser403 as ListModelsUser403
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUser404 as ListModelsUser404
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUser500 as ListModelsUser500
from pyfect.ai.openrouter.generated._schemas_1 import ListObservabilityDestinationsParams as ListObservabilityDestinationsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListObservabilityDestinations200 as ListObservabilityDestinations200
from pyfect.ai.openrouter.generated._schemas_1 import ListObservabilityDestinations400 as ListObservabilityDestinations400
from pyfect.ai.openrouter.generated._schemas_1 import ListObservabilityDestinations401 as ListObservabilityDestinations401
from pyfect.ai.openrouter.generated._schemas_1 import ListObservabilityDestinations500 as ListObservabilityDestinations500
from pyfect.ai.openrouter.generated._schemas_1 import CreateObservabilityDestinationParams as CreateObservabilityDestinationParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateObservabilityDestinationRequestJson as CreateObservabilityDestinationRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateObservabilityDestination201 as CreateObservabilityDestination201
from pyfect.ai.openrouter.generated._schemas_1 import CreateObservabilityDestination400 as CreateObservabilityDestination400
from pyfect.ai.openrouter.generated._schemas_1 import CreateObservabilityDestination401 as CreateObservabilityDestination401
from pyfect.ai.openrouter.generated._schemas_1 import CreateObservabilityDestination403 as CreateObservabilityDestination403
from pyfect.ai.openrouter.generated._schemas_1 import CreateObservabilityDestination409 as CreateObservabilityDestination409
from pyfect.ai.openrouter.generated._schemas_1 import CreateObservabilityDestination500 as CreateObservabilityDestination500
from pyfect.ai.openrouter.generated._schemas_1 import GetObservabilityDestinationParams as GetObservabilityDestinationParams
from pyfect.ai.openrouter.generated._schemas_1 import GetObservabilityDestination200 as GetObservabilityDestination200
from pyfect.ai.openrouter.generated._schemas_1 import GetObservabilityDestination401 as GetObservabilityDestination401
from pyfect.ai.openrouter.generated._schemas_1 import GetObservabilityDestination404 as GetObservabilityDestination404
from pyfect.ai.openrouter.generated._schemas_1 import GetObservabilityDestination500 as GetObservabilityDestination500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestinationParams as DeleteObservabilityDestinationParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestination200 as DeleteObservabilityDestination200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestination401 as DeleteObservabilityDestination401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestination404 as DeleteObservabilityDestination404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestination500 as DeleteObservabilityDestination500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestinationParams as UpdateObservabilityDestinationParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestinationRequestJson as UpdateObservabilityDestinationRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination200 as UpdateObservabilityDestination200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination400 as UpdateObservabilityDestination400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination401 as UpdateObservabilityDestination401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination404 as UpdateObservabilityDestination404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination409 as UpdateObservabilityDestination409
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination500 as UpdateObservabilityDestination500
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembersParams as ListOrganizationMembersParams
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembers200 as ListOrganizationMembers200
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembers401 as ListOrganizationMembers401
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembers404 as ListOrganizationMembers404
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembers500 as ListOrganizationMembers500
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetsParams as ListPresetsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets200 as ListPresets200
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets400 as ListPresets400
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets401 as ListPresets401
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets500 as ListPresets500
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetParams as GetPresetParams
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset200 as GetPreset200
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset400 as GetPreset400
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset401 as GetPreset401
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset404 as GetPreset404
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset500 as GetPreset500
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsChatCompletionsParams as CreatePresetsChatCompletionsParams
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsChatCompletionsRequestJson as CreatePresetsChatCompletionsRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsChatCompletions200 as CreatePresetsChatCompletions200
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsChatCompletions400 as CreatePresetsChatCompletions400
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsChatCompletions401 as CreatePresetsChatCompletions401
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsChatCompletions403 as CreatePresetsChatCompletions403
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsChatCompletions404 as CreatePresetsChatCompletions404
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsChatCompletions409 as CreatePresetsChatCompletions409
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsChatCompletions500 as CreatePresetsChatCompletions500
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsMessagesParams as CreatePresetsMessagesParams
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsMessagesRequestJson as CreatePresetsMessagesRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsMessages200 as CreatePresetsMessages200
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsMessages400 as CreatePresetsMessages400
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsMessages401 as CreatePresetsMessages401
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsMessages403 as CreatePresetsMessages403
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsMessages404 as CreatePresetsMessages404
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsMessages409 as CreatePresetsMessages409
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsMessages500 as CreatePresetsMessages500
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsResponsesParams as CreatePresetsResponsesParams
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsResponsesRequestJson as CreatePresetsResponsesRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsResponses200 as CreatePresetsResponses200
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsResponses400 as CreatePresetsResponses400
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsResponses401 as CreatePresetsResponses401
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsResponses403 as CreatePresetsResponses403
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsResponses404 as CreatePresetsResponses404
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsResponses409 as CreatePresetsResponses409
from pyfect.ai.openrouter.generated._schemas_1 import CreatePresetsResponses500 as CreatePresetsResponses500
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersionsParams as ListPresetVersionsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions200 as ListPresetVersions200
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions400 as ListPresetVersions400
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions401 as ListPresetVersions401
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions404 as ListPresetVersions404
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions500 as ListPresetVersions500
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersionParams as GetPresetVersionParams
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion200 as GetPresetVersion200
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion400 as GetPresetVersion400
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion401 as GetPresetVersion401
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion404 as GetPresetVersion404
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion500 as GetPresetVersion500
from pyfect.ai.openrouter.generated._schemas_1 import ListProvidersParams as ListProvidersParams
from pyfect.ai.openrouter.generated._schemas_1 import ListProviders200 as ListProviders200
from pyfect.ai.openrouter.generated._schemas_1 import ListProviders500 as ListProviders500
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerankParams as CreateRerankParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerankRequestJson as CreateRerankRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank200 as CreateRerank200
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank200Sse as CreateRerank200Sse
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank400 as CreateRerank400
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank401 as CreateRerank401
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank402 as CreateRerank402
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank404 as CreateRerank404
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank429 as CreateRerank429
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank500 as CreateRerank500
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank502 as CreateRerank502
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank503 as CreateRerank503
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank524 as CreateRerank524
from pyfect.ai.openrouter.generated._schemas_1 import CreateRerank529 as CreateRerank529
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponsesParams as CreateResponsesParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponsesRequestJson as CreateResponsesRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses200 as CreateResponses200
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses200Sse as CreateResponses200Sse
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses400 as CreateResponses400
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses401 as CreateResponses401
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses402 as CreateResponses402
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses403 as CreateResponses403
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses404 as CreateResponses404
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses408 as CreateResponses408
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses413 as CreateResponses413
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses422 as CreateResponses422
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses429 as CreateResponses429
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses500 as CreateResponses500
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses502 as CreateResponses502
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses503 as CreateResponses503
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses524 as CreateResponses524
from pyfect.ai.openrouter.generated._schemas_1 import CreateResponses529 as CreateResponses529
from pyfect.ai.openrouter.generated._schemas_1 import CreateVideosParams as CreateVideosParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateVideosRequestJson as CreateVideosRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateVideos202 as CreateVideos202
from pyfect.ai.openrouter.generated._schemas_1 import CreateVideos400 as CreateVideos400
from pyfect.ai.openrouter.generated._schemas_1 import CreateVideos401 as CreateVideos401
from pyfect.ai.openrouter.generated._schemas_1 import CreateVideos402 as CreateVideos402
from pyfect.ai.openrouter.generated._schemas_1 import CreateVideos404 as CreateVideos404
from pyfect.ai.openrouter.generated._schemas_1 import CreateVideos429 as CreateVideos429
from pyfect.ai.openrouter.generated._schemas_1 import CreateVideos500 as CreateVideos500
from pyfect.ai.openrouter.generated._schemas_1 import GetVideosParams as GetVideosParams
from pyfect.ai.openrouter.generated._schemas_1 import GetVideos200 as GetVideos200
from pyfect.ai.openrouter.generated._schemas_1 import GetVideos401 as GetVideos401
from pyfect.ai.openrouter.generated._schemas_1 import GetVideos404 as GetVideos404
from pyfect.ai.openrouter.generated._schemas_1 import GetVideos500 as GetVideos500
from pyfect.ai.openrouter.generated._schemas_1 import ListVideosContentParams as ListVideosContentParams
from pyfect.ai.openrouter.generated._schemas_1 import ListVideosContent400 as ListVideosContent400
from pyfect.ai.openrouter.generated._schemas_1 import ListVideosContent401 as ListVideosContent401
from pyfect.ai.openrouter.generated._schemas_1 import ListVideosContent404 as ListVideosContent404
from pyfect.ai.openrouter.generated._schemas_1 import ListVideosContent500 as ListVideosContent500
from pyfect.ai.openrouter.generated._schemas_1 import ListVideosContent502 as ListVideosContent502
from pyfect.ai.openrouter.generated._schemas_1 import ListVideosModelsParams as ListVideosModelsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListVideosModels200 as ListVideosModels200
from pyfect.ai.openrouter.generated._schemas_1 import ListVideosModels400 as ListVideosModels400
from pyfect.ai.openrouter.generated._schemas_1 import ListVideosModels500 as ListVideosModels500
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspacesParams as ListWorkspacesParams
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaces200 as ListWorkspaces200
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaces401 as ListWorkspaces401
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaces500 as ListWorkspaces500
from pyfect.ai.openrouter.generated._schemas_1 import CreateWorkspaceParams as CreateWorkspaceParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateWorkspaceRequestJson as CreateWorkspaceRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateWorkspace201 as CreateWorkspace201
from pyfect.ai.openrouter.generated._schemas_1 import CreateWorkspace400 as CreateWorkspace400
from pyfect.ai.openrouter.generated._schemas_1 import CreateWorkspace401 as CreateWorkspace401
from pyfect.ai.openrouter.generated._schemas_1 import CreateWorkspace403 as CreateWorkspace403
from pyfect.ai.openrouter.generated._schemas_1 import CreateWorkspace500 as CreateWorkspace500
from pyfect.ai.openrouter.generated._schemas_1 import GetWorkspaceParams as GetWorkspaceParams
from pyfect.ai.openrouter.generated._schemas_1 import GetWorkspace200 as GetWorkspace200
from pyfect.ai.openrouter.generated._schemas_1 import GetWorkspace401 as GetWorkspace401
from pyfect.ai.openrouter.generated._schemas_1 import GetWorkspace404 as GetWorkspace404
from pyfect.ai.openrouter.generated._schemas_1 import GetWorkspace500 as GetWorkspace500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspaceParams as DeleteWorkspaceParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspace200 as DeleteWorkspace200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspace400 as DeleteWorkspace400
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspace401 as DeleteWorkspace401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspace403 as DeleteWorkspace403
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspace404 as DeleteWorkspace404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspace500 as DeleteWorkspace500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateWorkspaceParams as UpdateWorkspaceParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateWorkspaceRequestJson as UpdateWorkspaceRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateWorkspace200 as UpdateWorkspace200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateWorkspace400 as UpdateWorkspace400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateWorkspace401 as UpdateWorkspace401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateWorkspace403 as UpdateWorkspace403
from pyfect.ai.openrouter.generated._schemas_1 import UpdateWorkspace404 as UpdateWorkspace404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateWorkspace500 as UpdateWorkspace500
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceBudgetsParams as ListWorkspaceBudgetsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceBudgets200 as ListWorkspaceBudgets200
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceBudgets401 as ListWorkspaceBudgets401
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceBudgets404 as ListWorkspaceBudgets404
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceBudgets500 as ListWorkspaceBudgets500
from pyfect.ai.openrouter.generated._schemas_1 import UpsertWorkspaceBudgetParams as UpsertWorkspaceBudgetParams
from pyfect.ai.openrouter.generated._schemas_1 import UpsertWorkspaceBudgetRequestJson as UpsertWorkspaceBudgetRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpsertWorkspaceBudget200 as UpsertWorkspaceBudget200
from pyfect.ai.openrouter.generated._schemas_1 import UpsertWorkspaceBudget400 as UpsertWorkspaceBudget400
from pyfect.ai.openrouter.generated._schemas_1 import UpsertWorkspaceBudget401 as UpsertWorkspaceBudget401
from pyfect.ai.openrouter.generated._schemas_1 import UpsertWorkspaceBudget404 as UpsertWorkspaceBudget404
from pyfect.ai.openrouter.generated._schemas_1 import UpsertWorkspaceBudget500 as UpsertWorkspaceBudget500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspaceBudgetParams as DeleteWorkspaceBudgetParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspaceBudget200 as DeleteWorkspaceBudget200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspaceBudget401 as DeleteWorkspaceBudget401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspaceBudget404 as DeleteWorkspaceBudget404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteWorkspaceBudget500 as DeleteWorkspaceBudget500
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceMembersParams as ListWorkspaceMembersParams
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceMembers200 as ListWorkspaceMembers200
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceMembers401 as ListWorkspaceMembers401
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceMembers403 as ListWorkspaceMembers403
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceMembers404 as ListWorkspaceMembers404
from pyfect.ai.openrouter.generated._schemas_1 import ListWorkspaceMembers500 as ListWorkspaceMembers500
from pyfect.ai.openrouter.generated._schemas_1 import BulkAddWorkspaceMembersParams as BulkAddWorkspaceMembersParams
from pyfect.ai.openrouter.generated._schemas_1 import BulkAddWorkspaceMembersRequestJson as BulkAddWorkspaceMembersRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import BulkAddWorkspaceMembers200 as BulkAddWorkspaceMembers200
from pyfect.ai.openrouter.generated._schemas_1 import BulkAddWorkspaceMembers400 as BulkAddWorkspaceMembers400
from pyfect.ai.openrouter.generated._schemas_1 import BulkAddWorkspaceMembers401 as BulkAddWorkspaceMembers401
from pyfect.ai.openrouter.generated._schemas_1 import BulkAddWorkspaceMembers403 as BulkAddWorkspaceMembers403
from pyfect.ai.openrouter.generated._schemas_1 import BulkAddWorkspaceMembers404 as BulkAddWorkspaceMembers404
from pyfect.ai.openrouter.generated._schemas_1 import BulkAddWorkspaceMembers500 as BulkAddWorkspaceMembers500
from pyfect.ai.openrouter.generated._schemas_1 import BulkRemoveWorkspaceMembersParams as BulkRemoveWorkspaceMembersParams
from pyfect.ai.openrouter.generated._schemas_1 import BulkRemoveWorkspaceMembersRequestJson as BulkRemoveWorkspaceMembersRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import BulkRemoveWorkspaceMembers200 as BulkRemoveWorkspaceMembers200
from pyfect.ai.openrouter.generated._schemas_1 import BulkRemoveWorkspaceMembers400 as BulkRemoveWorkspaceMembers400
from pyfect.ai.openrouter.generated._schemas_1 import BulkRemoveWorkspaceMembers401 as BulkRemoveWorkspaceMembers401
from pyfect.ai.openrouter.generated._schemas_1 import BulkRemoveWorkspaceMembers403 as BulkRemoveWorkspaceMembers403
from pyfect.ai.openrouter.generated._schemas_1 import BulkRemoveWorkspaceMembers404 as BulkRemoveWorkspaceMembers404
from pyfect.ai.openrouter.generated._schemas_1 import BulkRemoveWorkspaceMembers500 as BulkRemoveWorkspaceMembers500

__all__ = [
    "AABenchmarkEntry",
    "ActivityItem",
    "ActivityResponse",
    "AdditionalToolsItem",
    "AdvisorNestedTool",
    "AdvisorReasoning",
    "AdvisorServerToolConfig",
    "AdvisorServerTool_OpenRouter",
    "AgentMessageItem",
    "AnnotationAddedEvent",
    "AnthropicAdvisorMessageUsageIteration",
    "AnthropicAdvisorToolResult",
    "AnthropicAllowedCallers",
    "AnthropicBase64ImageSource",
    "AnthropicBase64PdfSource",
    "AnthropicBaseUsageIteration",
    "AnthropicBashCodeExecutionContent",
    "AnthropicBashCodeExecutionOutput",
    "AnthropicBashCodeExecutionResult",
    "AnthropicBashCodeExecutionToolResult",
    "AnthropicBashCodeExecutionToolResultError",
    "AnthropicCacheControlDirective",
    "AnthropicCacheControlTtl",
    "AnthropicCacheCreation",
    "AnthropicCaller",
    "AnthropicCitationCharLocation",
    "AnthropicCitationCharLocationParam",
    "AnthropicCitationContentBlockLocation",
    "AnthropicCitationContentBlockLocationParam",
    "AnthropicCitationPageLocation",
    "AnthropicCitationPageLocationParam",
    "AnthropicCitationSearchResultLocation",
    "AnthropicCitationSearchResultLocationParam",
    "AnthropicCitationWebSearchResultLocation",
    "AnthropicCitationWebSearchResultLocationParam",
    "AnthropicCitationsConfig",
    "AnthropicCodeExecution20250825Caller",
    "AnthropicCodeExecution20260120Caller",
    "AnthropicCodeExecutionContent",
    "AnthropicCodeExecutionOutput",
    "AnthropicCodeExecutionResult",
    "AnthropicCodeExecutionToolResult",
    "AnthropicCodeExecutionToolResultError",
    "AnthropicCompactionBlock",
    "AnthropicCompactionUsageIteration",
    "AnthropicContainer",
    "AnthropicContainerUpload",
    "AnthropicDirectCaller",
    "AnthropicDocumentBlock",
    "AnthropicDocumentBlockParam",
    "AnthropicEncryptedCodeExecutionResult",
    "AnthropicFileDocumentSource",
    "AnthropicImageBlockParam",
    "AnthropicImageMimeType",
    "AnthropicInputTokensClearAtLeast",
    "AnthropicInputTokensTrigger",
    "AnthropicIterationCacheCreation",
    "AnthropicMessageUsageIteration",
    "AnthropicOutputTokensDetails",
    "AnthropicPlainTextSource",
    "AnthropicRedactedThinkingBlock",
    "AnthropicRefusalStopDetails",
    "AnthropicSearchResultBlockParam",
    "AnthropicServerToolErrorCode",
    "AnthropicServerToolUsage",
    "AnthropicServiceTier",
    "AnthropicSpeed",
    "AnthropicTextBlock",
    "AnthropicTextBlockParam",
    "AnthropicTextCitation",
    "AnthropicTextEditorCodeExecutionContent",
    "AnthropicTextEditorCodeExecutionCreateResult",
    "AnthropicTextEditorCodeExecutionStrReplaceResult",
    "AnthropicTextEditorCodeExecutionToolResult",
    "AnthropicTextEditorCodeExecutionToolResultError",
    "AnthropicTextEditorCodeExecutionViewResult",
    "AnthropicThinkingBlock",
    "AnthropicThinkingDisplay",
    "AnthropicThinkingTurns",
    "AnthropicToolReference",
    "AnthropicToolSearchContent",
    "AnthropicToolSearchResult",
    "AnthropicToolSearchResultError",
    "AnthropicToolSearchToolBm25",
    "AnthropicToolSearchToolRegex",
    "AnthropicToolSearchToolResult",
    "AnthropicToolUseBlock",
    "AnthropicToolUsesKeep",
    "AnthropicToolUsesTrigger",
    "AnthropicUnknownUsageIteration",
    "AnthropicUrlImageSource",
    "AnthropicUrlPdfSource",
    "AnthropicUsage",
    "AnthropicUsageIteration",
    "AnthropicWebFetchBlock",
    "AnthropicWebFetchContent",
    "AnthropicWebFetchToolResult",
    "AnthropicWebFetchToolResultError",
    "AnthropicWebSearchResult",
    "AnthropicWebSearchResultBlockParam",
    "AnthropicWebSearchToolResult",
    "AnthropicWebSearchToolResultError",
    "AnthropicWebSearchToolUserLocation",
    "ApiErrorType",
    "AppRankingsItem",
    "AppRankingsResponse",
    "ApplyPatchCallItem",
    "ApplyPatchCallOperation",
    "ApplyPatchCallOperationDiffDeltaEvent",
    "ApplyPatchCallOperationDiffDoneEvent",
    "ApplyPatchCallOutputItem",
    "ApplyPatchCallStatus",
    "ApplyPatchCreateFileOperation",
    "ApplyPatchDeleteFileOperation",
    "ApplyPatchEngineEnum",
    "ApplyPatchServerTool",
    "ApplyPatchServerToolConfig",
    "ApplyPatchServerTool_OpenRouter",
    "ApplyPatchUpdateFileOperation",
    "Arrays_",
    "Arrays_1",
    "Arrays_10",
    "Arrays_11",
    "Arrays_12",
    "Arrays_13",
    "Arrays_14",
    "Arrays_15",
    "Arrays_16",
    "Arrays_17",
    "Arrays_18",
    "Arrays_2",
    "Arrays_3",
    "Arrays_4",
    "Arrays_5",
    "Arrays_6",
    "Arrays_7",
    "Arrays_8",
    "Arrays_9",
    "AutoBetaRouterPlugin",
    "AutoRouterPlugin",
    "BYOKKey",
    "BYOKProviderSlug",
    "BadGatewayResponse",
    "BadGatewayResponseErrorData",
    "BadRequestResponse",
    "BadRequestResponseErrorData",
    "BaseAnnotationAddedEvent",
    "BaseContentPartAddedEvent",
    "BaseContentPartDoneEvent",
    "BaseCustomToolCallInputDeltaEvent",
    "BaseCustomToolCallInputDoneEvent",
    "BaseErrorEvent",
    "BaseFunctionCallArgsDeltaEvent",
    "BaseFunctionCallArgsDoneEvent",
    "BaseInputs",
    "BaseMessagesResult",
    "BaseReasoningConfig",
    "BaseReasoningDeltaEvent",
    "BaseReasoningDoneEvent",
    "BaseReasoningSummaryPartAddedEvent",
    "BaseReasoningSummaryPartDoneEvent",
    "BaseReasoningSummaryTextDeltaEvent",
    "BaseReasoningSummaryTextDoneEvent",
    "BaseRefusalDeltaEvent",
    "BaseRefusalDoneEvent",
    "BaseResponsesResult",
    "BaseTextDeltaEvent",
    "BaseTextDoneEvent",
    "BashServerTool",
    "BashServerToolConfig",
    "BashServerToolEngine",
    "BashServerToolEnvironment",
    "BooleanCapability",
    "BulkAddWorkspaceMembers200",
    "BulkAddWorkspaceMembers400",
    "BulkAddWorkspaceMembers401",
    "BulkAddWorkspaceMembers403",
    "BulkAddWorkspaceMembers404",
    "BulkAddWorkspaceMembers500",
    "BulkAddWorkspaceMembersParams",
    "BulkAddWorkspaceMembersRequest",
    "BulkAddWorkspaceMembersRequestJson",
    "BulkAddWorkspaceMembersResponse",
    "BulkAssignKeysRequest",
    "BulkAssignKeysResponse",
    "BulkAssignKeysToGuardrail200",
    "BulkAssignKeysToGuardrail400",
    "BulkAssignKeysToGuardrail401",
    "BulkAssignKeysToGuardrail404",
    "BulkAssignKeysToGuardrail500",
    "BulkAssignKeysToGuardrailParams",
    "BulkAssignKeysToGuardrailRequestJson",
    "BulkAssignMembersRequest",
    "BulkAssignMembersResponse",
    "BulkAssignMembersToGuardrail200",
    "BulkAssignMembersToGuardrail400",
    "BulkAssignMembersToGuardrail401",
    "BulkAssignMembersToGuardrail404",
    "BulkAssignMembersToGuardrail500",
    "BulkAssignMembersToGuardrailParams",
    "BulkAssignMembersToGuardrailRequestJson",
    "BulkRemoveWorkspaceMembers200",
    "BulkRemoveWorkspaceMembers400",
    "BulkRemoveWorkspaceMembers401",
    "BulkRemoveWorkspaceMembers403",
    "BulkRemoveWorkspaceMembers404",
    "BulkRemoveWorkspaceMembers500",
    "BulkRemoveWorkspaceMembersParams",
    "BulkRemoveWorkspaceMembersRequest",
    "BulkRemoveWorkspaceMembersRequestJson",
    "BulkRemoveWorkspaceMembersResponse",
    "BulkUnassignKeysFromGuardrail200",
    "BulkUnassignKeysFromGuardrail400",
    "BulkUnassignKeysFromGuardrail401",
    "BulkUnassignKeysFromGuardrail404",
    "BulkUnassignKeysFromGuardrail500",
    "BulkUnassignKeysFromGuardrailParams",
    "BulkUnassignKeysFromGuardrailRequestJson",
    "BulkUnassignKeysRequest",
    "BulkUnassignKeysResponse",
    "BulkUnassignMembersFromGuardrail200",
    "BulkUnassignMembersFromGuardrail400",
    "BulkUnassignMembersFromGuardrail401",
    "BulkUnassignMembersFromGuardrail404",
    "BulkUnassignMembersFromGuardrail500",
    "BulkUnassignMembersFromGuardrailParams",
    "BulkUnassignMembersFromGuardrailRequestJson",
    "BulkUnassignMembersRequest",
    "BulkUnassignMembersResponse",
    "CapabilityDescriptor",
    "ChatAssistantImages",
    "ChatAssistantMessage",
    "ChatAudioOutput",
    "ChatChoice",
    "ChatContentAudio",
    "ChatContentCacheControl",
    "ChatContentFile",
    "ChatContentImage",
    "ChatContentItems",
    "ChatContentText",
    "ChatContentVideo",
    "ChatContentVideoInput",
    "ChatDebugOptions",
    "ChatDeveloperMessage",
    "ChatFinishReasonEnum",
    "ChatFormatGrammarConfig",
    "ChatFormatJsonObjectConfig",
    "ChatFormatJsonSchemaConfig",
    "ChatFormatPythonConfig",
    "ChatFormatTextConfig",
    "ChatFunctionTool",
    "ChatJsonSchemaConfig",
    "ChatMessages",
    "ChatModelNames",
    "ChatNamedToolChoice",
    "ChatReasoningDetails",
    "ChatReasoningSummaryVerbosityEnum",
    "ChatRequest",
    "ChatResult",
    "ChatSearchModelsServerTool",
    "ChatServerToolChoice",
    "ChatStreamChoice",
    "ChatStreamChunk",
    "ChatStreamDelta",
    "ChatStreamOptions",
    "ChatStreamReasoningDetails",
    "ChatStreamToolCall",
    "ChatStreamingResponse",
    "ChatSystemMessage",
    "ChatTokenLogprob",
    "ChatTokenLogprobs",
    "ChatToolCall",
    "ChatToolChoice",
    "ChatToolMessage",
    "ChatUsage",
    "ChatUserMessage",
    "ChatWebSearchShorthand",
    "CodeInterpreterCallItem",
    "CodeInterpreterServerTool",
    "CodexLocalShellTool",
    "CompactionItem",
    "CompletedEvent",
    "CompoundFilter",
    "ComputerUseServerTool",
    "ConflictResponse",
    "ConflictResponseErrorData",
    "ContainerAutoEnvironment",
    "ContainerReferenceEnvironment",
    "ContentFilterAction",
    "ContentFilterBuiltinAction",
    "ContentFilterBuiltinEntry",
    "ContentFilterBuiltinEntryInput",
    "ContentFilterBuiltinSlug",
    "ContentFilterEntry",
    "ContentPartAddedEvent",
    "ContentPartAudio",
    "ContentPartDoneEvent",
    "ContentPartImage",
    "ContentPartInputAudio",
    "ContentPartInputFile",
    "ContentPartInputVideo",
    "ContentPartVideo",
    "ContextCompactionItem",
    "ContextCompressionEngine",
    "ContextCompressionPlugin",
    "CostDetails",
    "CreateAudioSpeech400",
    "CreateAudioSpeech401",
    "CreateAudioSpeech402",
    "CreateAudioSpeech404",
    "CreateAudioSpeech429",
    "CreateAudioSpeech500",
    "CreateAudioSpeech502",
    "CreateAudioSpeech503",
    "CreateAudioSpeech524",
    "CreateAudioSpeech529",
    "CreateAudioSpeechParams",
    "CreateAudioSpeechRequestJson",
    "CreateAudioTranscriptions200",
    "CreateAudioTranscriptions400",
    "CreateAudioTranscriptions401",
    "CreateAudioTranscriptions402",
    "CreateAudioTranscriptions404",
    "CreateAudioTranscriptions429",
    "CreateAudioTranscriptions500",
    "CreateAudioTranscriptions502",
    "CreateAudioTranscriptions503",
    "CreateAudioTranscriptions524",
    "CreateAudioTranscriptions529",
    "CreateAudioTranscriptionsParams",
    "CreateAudioTranscriptionsRequestJson",
    "CreateAuthKeysCode200",
    "CreateAuthKeysCode400",
    "CreateAuthKeysCode401",
    "CreateAuthKeysCode403",
    "CreateAuthKeysCode409",
    "CreateAuthKeysCode500",
    "CreateAuthKeysCodeParams",
    "CreateAuthKeysCodeRequestJson",
    "CreateBYOKKey201",
    "CreateBYOKKey400",
    "CreateBYOKKey401",
    "CreateBYOKKey403",
    "CreateBYOKKey500",
    "CreateBYOKKeyParams",
    "CreateBYOKKeyRequest",
    "CreateBYOKKeyRequestJson",
    "CreateBYOKKeyResponse",
    "CreateCoinbaseCharge410",
    "CreateCoinbaseChargeParams",
    "CreateEmbeddings200",
    "CreateEmbeddings200Sse",
    "CreateEmbeddings400",
    "CreateEmbeddings401",
    "CreateEmbeddings402",
    "CreateEmbeddings404",
    "CreateEmbeddings429",
    "CreateEmbeddings500",
    "CreateEmbeddings502",
    "CreateEmbeddings503",
    "CreateEmbeddings524",
    "CreateEmbeddings529",
    "CreateEmbeddingsParams",
    "CreateEmbeddingsRequestJson",
    "CreateGuardrail201",
    "CreateGuardrail400",
    "CreateGuardrail401",
    "CreateGuardrail403",
    "CreateGuardrail500",
    "CreateGuardrailParams",
    "CreateGuardrailRequest",
    "CreateGuardrailRequestJson",
    "CreateGuardrailResponse",
    "CreateImages200",
    "CreateImages200Sse",
    "CreateImages400",
    "CreateImages401",
    "CreateImages402",
    "CreateImages403",
    "CreateImages404",
    "CreateImages413",
    "CreateImages429",
    "CreateImages500",
    "CreateImages502",
    "CreateImages524",
    "CreateImages529",
    "CreateImagesParams",
    "CreateImagesRequestJson",
    "CreateKeys201",
    "CreateKeys400",
    "CreateKeys401",
    "CreateKeys403",
    "CreateKeys429",
    "CreateKeys500",
    "CreateKeysParams",
    "CreateKeysRequestJson",
    "CreateMessages200",
    "CreateMessages200Sse",
    "CreateMessages400",
    "CreateMessages401",
    "CreateMessages403",
    "CreateMessages404",
    "CreateMessages429",
    "CreateMessages500",
    "CreateMessages503",
    "CreateMessages529",
    "CreateMessagesParams",
    "CreateMessagesRequestJson",
    "CreateObservabilityDestination201",
    "CreateObservabilityDestination400",
    "CreateObservabilityDestination401",
    "CreateObservabilityDestination403",
    "CreateObservabilityDestination409",
    "CreateObservabilityDestination500",
    "CreateObservabilityDestinationParams",
    "CreateObservabilityDestinationRequest",
    "CreateObservabilityDestinationRequestJson",
    "CreateObservabilityDestinationResponse",
    "CreatePresetFromInferenceResponse",
    "CreatePresetsChatCompletions200",
    "CreatePresetsChatCompletions400",
    "CreatePresetsChatCompletions401",
    "CreatePresetsChatCompletions403",
    "CreatePresetsChatCompletions404",
    "CreatePresetsChatCompletions409",
    "CreatePresetsChatCompletions500",
    "CreatePresetsChatCompletionsParams",
    "CreatePresetsChatCompletionsRequestJson",
    "CreatePresetsMessages200",
    "CreatePresetsMessages400",
    "CreatePresetsMessages401",
    "CreatePresetsMessages403",
    "CreatePresetsMessages404",
    "CreatePresetsMessages409",
    "CreatePresetsMessages500",
    "CreatePresetsMessagesParams",
    "CreatePresetsMessagesRequestJson",
    "CreatePresetsResponses200",
    "CreatePresetsResponses400",
    "CreatePresetsResponses401",
    "CreatePresetsResponses403",
    "CreatePresetsResponses404",
    "CreatePresetsResponses409",
    "CreatePresetsResponses500",
    "CreatePresetsResponsesParams",
    "CreatePresetsResponsesRequestJson",
    "CreateRerank200",
    "CreateRerank200Sse",
    "CreateRerank400",
    "CreateRerank401",
    "CreateRerank402",
    "CreateRerank404",
    "CreateRerank429",
    "CreateRerank500",
    "CreateRerank502",
    "CreateRerank503",
    "CreateRerank524",
    "CreateRerank529",
    "CreateRerankParams",
    "CreateRerankRequestJson",
    "CreateResponses200",
    "CreateResponses200Sse",
    "CreateResponses400",
    "CreateResponses401",
    "CreateResponses402",
    "CreateResponses403",
    "CreateResponses404",
    "CreateResponses408",
    "CreateResponses413",
    "CreateResponses422",
    "CreateResponses429",
    "CreateResponses500",
    "CreateResponses502",
    "CreateResponses503",
    "CreateResponses524",
    "CreateResponses529",
    "CreateResponsesParams",
    "CreateResponsesRequestJson",
    "CreateVideos202",
    "CreateVideos400",
    "CreateVideos401",
    "CreateVideos402",
    "CreateVideos404",
    "CreateVideos429",
    "CreateVideos500",
    "CreateVideosParams",
    "CreateVideosRequestJson",
    "CreateWorkspace201",
    "CreateWorkspace400",
    "CreateWorkspace401",
    "CreateWorkspace403",
    "CreateWorkspace500",
    "CreateWorkspaceParams",
    "CreateWorkspaceRequest",
    "CreateWorkspaceRequestJson",
    "CreateWorkspaceResponse",
    "CreatedEvent",
    "CustomTool",
    "CustomToolCallInputDeltaEvent",
    "CustomToolCallInputDoneEvent",
    "CustomToolCallItem",
    "CustomToolCallOutputItem",
    "DABenchmarkEntry",
    "DatetimeServerTool",
    "DatetimeServerToolConfig",
    "DebugEvent",
    "DefaultParameters",
    "DeleteBYOKKey200",
    "DeleteBYOKKey401",
    "DeleteBYOKKey404",
    "DeleteBYOKKey500",
    "DeleteBYOKKeyParams",
    "DeleteBYOKKeyResponse",
    "DeleteFile200",
    "DeleteFile401",
    "DeleteFile404",
    "DeleteFile429",
    "DeleteFile500",
    "DeleteFileParams",
    "DeleteGuardrail200",
    "DeleteGuardrail401",
    "DeleteGuardrail404",
    "DeleteGuardrail500",
    "DeleteGuardrailParams",
    "DeleteGuardrailResponse",
    "DeleteKeys200",
    "DeleteKeys401",
    "DeleteKeys404",
    "DeleteKeys429",
    "DeleteKeys500",
    "DeleteKeysParams",
    "DeleteObservabilityDestination200",
    "DeleteObservabilityDestination401",
    "DeleteObservabilityDestination404",
    "DeleteObservabilityDestination500",
    "DeleteObservabilityDestinationParams",
    "DeleteObservabilityDestinationResponse",
    "DeleteWorkspace200",
    "DeleteWorkspace400",
    "DeleteWorkspace401",
    "DeleteWorkspace403",
    "DeleteWorkspace404",
    "DeleteWorkspace500",
    "DeleteWorkspaceBudget200",
    "DeleteWorkspaceBudget401",
    "DeleteWorkspaceBudget404",
    "DeleteWorkspaceBudget500",
    "DeleteWorkspaceBudgetParams",
    "DeleteWorkspaceBudgetResponse",
    "DeleteWorkspaceParams",
    "DeleteWorkspaceResponse",
    "DeprecatedRoute",
    "DownloadFileContent400",
    "DownloadFileContent401",
    "DownloadFileContent404",
    "DownloadFileContent429",
    "DownloadFileContent500",
    "DownloadFileContentParams",
    "EasyInputMessage",
    "EdgeNetworkTimeoutResponse",
    "EdgeNetworkTimeoutResponseErrorData",
    "EndpointInfo",
    "EndpointStatus",
    "EndpointsMetadata",
    "EnumCapability",
    "ErrorEvent",
    "ExchangeAuthCodeForAPIKey200",
    "ExchangeAuthCodeForAPIKey400",
    "ExchangeAuthCodeForAPIKey403",
    "ExchangeAuthCodeForAPIKey500",
    "ExchangeAuthCodeForAPIKeyParams",
    "ExchangeAuthCodeForAPIKeyRequestJson",
    "FailedEvent",
    "FileCitation",
    "FileDeleteResponse",
    "FileListResponse",
    "FileMetadata",
    "FileParserPlugin",
    "FilePath",
    "FileSearchServerTool",
    "FilesServerTool",
    "FilesServerToolConfig",
    "ForbiddenResponse",
    "ForbiddenResponseErrorData",
    "FormatJsonObjectConfig",
    "FormatJsonSchemaConfig",
    "FormatTextConfig",
    "Formats",
    "FrameImage",
    "FunctionCallArgsDeltaEvent",
    "FunctionCallArgsDoneEvent",
    "FunctionCallItem",
    "FunctionCallOutputItem",
    "FunctionTool",
    "FusionAnalysisResult",
    "FusionCallAnalysisCompletedEvent",
    "FusionCallAnalysisInProgressEvent",
    "FusionCallCompletedEvent",
    "FusionCallInProgressEvent",
    "FusionCallPanelAddedEvent",
    "FusionCallPanelCompletedEvent",
    "FusionCallPanelDeltaEvent",
    "FusionCallPanelFailedEvent",
    "FusionCallPanelReasoningDeltaEvent",
    "FusionPlugin",
    "FusionServerToolConfig",
    "FusionServerTool_OpenRouter",
    "FusionSource",
    "GenerationContentData",
    "GenerationContentResponse",
    "GenerationResponse",
    "GetAnalyticsMeta200",
    "GetAnalyticsMeta401",
    "GetAnalyticsMeta403",
    "GetAnalyticsMeta500",
    "GetAnalyticsMetaParams",
    "GetAppRankings200",
    "GetAppRankings400",
    "GetAppRankings401",
    "GetAppRankings429",
    "GetAppRankings500",
    "GetAppRankingsParams",
    "GetBYOKKey200",
    "GetBYOKKey401",
    "GetBYOKKey404",
    "GetBYOKKey500",
    "GetBYOKKeyParams",
    "GetBYOKKeyResponse",
    "GetBenchmarks200",
    "GetBenchmarks400",
    "GetBenchmarks401",
    "GetBenchmarks429",
    "GetBenchmarks500",
    "GetBenchmarksParams",
    "GetCredits200",
    "GetCredits401",
    "GetCredits403",
    "GetCredits500",
    "GetCreditsParams",
    "GetCurrentKey200",
    "GetCurrentKey401",
    "GetCurrentKey500",
    "GetCurrentKeyParams",
    "GetFileMetadata200",
    "GetFileMetadata401",
    "GetFileMetadata404",
    "GetFileMetadata429",
    "GetFileMetadata500",
    "GetFileMetadataParams",
    "GetGeneration200",
    "GetGeneration401",
    "GetGeneration402",
    "GetGeneration404",
    "GetGeneration429",
    "GetGeneration500",
    "GetGeneration502",
    "GetGeneration524",
    "GetGeneration529",
    "GetGenerationParams",
    "GetGuardrail200",
    "GetGuardrail401",
    "GetGuardrail404",
    "GetGuardrail500",
    "GetGuardrailParams",
    "GetGuardrailResponse",
    "GetKey200",
    "GetKey401",
    "GetKey404",
    "GetKey429",
    "GetKey500",
    "GetKeyParams",
    "GetModel200",
    "GetModel403",
    "GetModel404",
    "GetModel500",
    "GetModelParams",
    "GetModels200",
    "GetModels400",
    "GetModels403",
    "GetModels500",
    "GetModelsParams",
    "GetObservabilityDestination200",
    "GetObservabilityDestination401",
    "GetObservabilityDestination404",
    "GetObservabilityDestination500",
    "GetObservabilityDestinationParams",
    "GetObservabilityDestinationResponse",
    "GetPreset200",
    "GetPreset400",
    "GetPreset401",
    "GetPreset404",
    "GetPreset500",
    "GetPresetParams",
    "GetPresetResponse",
    "GetPresetVersion200",
    "GetPresetVersion400",
    "GetPresetVersion401",
    "GetPresetVersion404",
    "GetPresetVersion500",
    "GetPresetVersionParams",
    "GetPresetVersionResponse",
    "GetRankingsDaily200",
    "GetRankingsDaily400",
    "GetRankingsDaily401",
    "GetRankingsDaily429",
    "GetRankingsDaily500",
    "GetRankingsDailyParams",
    "GetTaskClassifications200",
    "GetTaskClassifications400",
    "GetTaskClassifications401",
    "GetTaskClassifications429",
    "GetTaskClassifications500",
    "GetTaskClassificationsParams",
    "GetUserActivity200",
    "GetUserActivity400",
    "GetUserActivity401",
    "GetUserActivity403",
    "GetUserActivity404",
    "GetUserActivity500",
    "GetUserActivityParams",
    "GetVideos200",
    "GetVideos401",
    "GetVideos404",
    "GetVideos500",
    "GetVideosParams",
    "GetWorkspace200",
    "GetWorkspace401",
    "GetWorkspace404",
    "GetWorkspace500",
    "GetWorkspaceParams",
    "GetWorkspaceResponse",
    "GoneResponse",
    "GoneResponseErrorData",
    "Guardrail",
    "GuardrailInterval",
    "ImageConfig",
    "ImageEndpoint",
    "ImageGenCallCompletedEvent",
    "ImageGenCallGeneratingEvent",
    "ImageGenCallInProgressEvent",
    "ImageGenCallPartialImageEvent",
    "ImageGenCompletedEvent",
    "ImageGenPartialImageEvent",
    "ImageGenStreamErrorEvent",
    "ImageGenTextChunkEvent",
    "ImageGenerationProviderPreferences",
    "ImageGenerationRequest",
    "ImageGenerationResponse",
    "ImageGenerationServerTool",
    "ImageGenerationServerToolConfig",
    "ImageGenerationServerTool_OpenRouter",
    "ImageGenerationStatus",
    "ImageGenerationUsage",
    "ImageInputModality",
    "ImageModelArchitecture",
    "ImageModelEndpointsResponse",
    "ImageModelListItem",
    "ImageModelsListResponse",
    "ImageOutputModality",
    "ImagePricingEntry",
    "ImageStreamingResponse",
    "InProgressEvent",
    "IncompleteDetails",
    "IncompleteEvent",
    "InputAudio",
    "InputFile",
    "InputImage",
    "InputMessageItem",
    "InputModality",
    "InputReference",
    "InputText",
    "InputVideo",
    "Inputs",
    "InstructType",
    "InternalServerResponse",
    "InternalServerResponseErrorData",
    "ItemReferenceItem",
    "KeyAssignment",
    "Legacy_ChatContentVideo",
    "Legacy_ChatContentVideoInput",
    "Legacy_WebSearchServerTool",
    "List200",
    "List400",
    "List401",
    "List429",
    "List500",
    "ListBYOKKeys200",
    "ListBYOKKeys400",
    "ListBYOKKeys401",
    "ListBYOKKeys500",
    "ListBYOKKeysParams",
    "ListBYOKKeysResponse",
    "ListEmbeddingsModels200",
    "ListEmbeddingsModels400",
    "ListEmbeddingsModels500",
    "ListEmbeddingsModelsParams",
    "ListEndpoints200",
    "ListEndpoints403",
    "ListEndpoints404",
    "ListEndpoints500",
    "ListEndpointsParams",
    "ListEndpointsResponse",
    "ListEndpointsZdr200",
    "ListEndpointsZdr403",
    "ListEndpointsZdr500",
    "ListEndpointsZdrParams",
    "ListFiles200",
    "ListFiles400",
    "ListFiles401",
    "ListFiles429",
    "ListFiles500",
    "ListFilesParams",
    "ListGenerationContent200",
    "ListGenerationContent401",
    "ListGenerationContent403",
    "ListGenerationContent404",
    "ListGenerationContent429",
    "ListGenerationContent500",
    "ListGenerationContent502",
    "ListGenerationContent524",
    "ListGenerationContent529",
    "ListGenerationContentParams",
    "ListGuardrailKeyAssignments200",
    "ListGuardrailKeyAssignments401",
    "ListGuardrailKeyAssignments404",
    "ListGuardrailKeyAssignments500",
    "ListGuardrailKeyAssignmentsParams",
    "ListGuardrailMemberAssignments200",
    "ListGuardrailMemberAssignments401",
    "ListGuardrailMemberAssignments404",
    "ListGuardrailMemberAssignments500",
    "ListGuardrailMemberAssignmentsParams",
    "ListGuardrails200",
    "ListGuardrails400",
    "ListGuardrails401",
    "ListGuardrails500",
    "ListGuardrailsParams",
    "ListGuardrailsResponse",
    "ListImageModelEndpoints200",
    "ListImageModelEndpoints404",
    "ListImageModelEndpoints500",
    "ListImageModelEndpointsParams",
    "ListImageModels200",
    "ListImageModels500",
    "ListImageModelsParams",
    "ListKeyAssignments200",
    "ListKeyAssignments401",
    "ListKeyAssignments500",
    "ListKeyAssignmentsParams",
    "ListKeyAssignmentsResponse",
    "ListMemberAssignments200",
    "ListMemberAssignments401",
    "ListMemberAssignments500",
    "ListMemberAssignmentsParams",
    "ListMemberAssignmentsResponse",
    "ListModelsCount200",
    "ListModelsCount400",
    "ListModelsCount403",
    "ListModelsCount500",
    "ListModelsCountParams",
    "ListModelsUser200",
    "ListModelsUser401",
    "ListModelsUser403",
    "ListModelsUser404",
    "ListModelsUser500",
    "ListModelsUserParams",
    "ListObservabilityDestinations200",
    "ListObservabilityDestinations400",
    "ListObservabilityDestinations401",
    "ListObservabilityDestinations500",
    "ListObservabilityDestinationsParams",
    "ListObservabilityDestinationsResponse",
    "ListOrganizationMembers200",
    "ListOrganizationMembers401",
    "ListOrganizationMembers404",
    "ListOrganizationMembers500",
    "ListOrganizationMembersParams",
    "ListParams",
    "ListPresetVersions200",
    "ListPresetVersions400",
    "ListPresetVersions401",
    "ListPresetVersions404",
    "ListPresetVersions500",
    "ListPresetVersionsParams",
    "ListPresetVersionsResponse",
    "ListPresets200",
    "ListPresets400",
    "ListPresets401",
    "ListPresets500",
    "ListPresetsParams",
    "ListPresetsResponse",
    "ListProviders200",
    "ListProviders500",
    "ListProvidersParams",
    "ListVideosContent400",
    "ListVideosContent401",
    "ListVideosContent404",
    "ListVideosContent500",
    "ListVideosContent502",
    "ListVideosContentParams",
    "ListVideosModels200",
    "ListVideosModels400",
    "ListVideosModels500",
    "ListVideosModelsParams",
    "ListWorkspaceBudgets200",
    "ListWorkspaceBudgets401",
    "ListWorkspaceBudgets404",
    "ListWorkspaceBudgets500",
    "ListWorkspaceBudgetsParams",
    "ListWorkspaceBudgetsResponse",
    "ListWorkspaceMembers200",
    "ListWorkspaceMembers401",
    "ListWorkspaceMembers403",
    "ListWorkspaceMembers404",
    "ListWorkspaceMembers500",
    "ListWorkspaceMembersParams",
    "ListWorkspaceMembersResponse",
    "ListWorkspaces200",
    "ListWorkspaces401",
    "ListWorkspaces500",
    "ListWorkspacesParams",
    "ListWorkspacesResponse",
    "LocalShellCallItem",
    "LocalShellCallOutputItem",
    "McpApprovalRequestItem",
    "McpApprovalResponseItem",
    "McpCallItem",
    "McpListToolsItem",
    "McpServerTool",
    "MemberAssignment",
    "MessagesAdvisorToolResultBlock",
    "MessagesContentBlockDeltaEvent",
    "MessagesContentBlockStartEvent",
    "MessagesContentBlockStopEvent",
    "MessagesDeltaEvent",
    "MessagesErrorDetail",
    "MessagesErrorEvent",
    "MessagesErrorResponse",
    "MessagesFallbackParam",
    "MessagesMessageParam",
    "MessagesOutputConfig",
    "MessagesPingEvent",
    "MessagesRequest",
    "MessagesResult",
    "MessagesSearchModelsServerTool",
    "MessagesStartEvent",
    "MessagesStopEvent",
    "MessagesStreamEvents",
    "MessagesStreamingResponse",
    "MetadataLevel",
    "Model",
    "ModelArchitecture",
    "ModelBenchmarks",
    "ModelGroup",
    "ModelLinks",
    "ModelName",
    "ModelReasoning",
    "ModelResponse",
    "ModelsCountResponse",
    "ModelsListResponse",
    "ModelsListResponseData",
    "ModerationPlugin",
    "MultimodalMedia",
    "NamespaceFunctionTool",
    "NamespaceTool",
    "NotFoundResponse",
    "NotFoundResponseErrorData",
    "ORAnthropicContentBlock",
    "ORAnthropicNullableCaller",
    "ORAnthropicServerToolUseBlock",
    "ORAnthropicStopReason",
    "Objects_",
    "Objects_1",
    "Objects_10",
    "Objects_100",
    "Objects_101",
    "Objects_102",
    "Objects_103",
    "Objects_104",
    "Objects_105",
    "Objects_106",
    "Objects_107",
    "Objects_108",
    "Objects_109",
    "Objects_11",
    "Objects_110",
    "Objects_111",
    "Objects_112",
    "Objects_113",
    "Objects_114",
    "Objects_115",
    "Objects_116",
    "Objects_117",
    "Objects_118",
    "Objects_119",
    "Objects_12",
    "Objects_120",
    "Objects_121",
    "Objects_122",
    "Objects_123",
    "Objects_124",
    "Objects_125",
    "Objects_126",
    "Objects_127",
    "Objects_128",
    "Objects_129",
    "Objects_13",
    "Objects_130",
    "Objects_131",
    "Objects_132",
    "Objects_133",
    "Objects_134",
    "Objects_135",
    "Objects_136",
    "Objects_137",
    "Objects_138",
    "Objects_139",
    "Objects_14",
    "Objects_140",
    "Objects_141",
    "Objects_142",
    "Objects_143",
    "Objects_144",
    "Objects_145",
    "Objects_146",
    "Objects_147",
    "Objects_148",
    "Objects_149",
    "Objects_15",
    "Objects_150",
    "Objects_151",
    "Objects_152",
    "Objects_153",
    "Objects_16",
    "Objects_17",
    "Objects_18",
    "Objects_19",
    "Objects_2",
    "Objects_20",
    "Objects_21",
    "Objects_22",
    "Objects_23",
    "Objects_24",
    "Objects_25",
    "Objects_26",
    "Objects_27",
    "Objects_28",
    "Objects_29",
    "Objects_3",
    "Objects_30",
    "Objects_31",
    "Objects_32",
    "Objects_33",
    "Objects_34",
    "Objects_35",
    "Objects_36",
    "Objects_37",
    "Objects_38",
    "Objects_39",
    "Objects_4",
    "Objects_40",
    "Objects_41",
    "Objects_42",
    "Objects_43",
    "Objects_44",
    "Objects_45",
    "Objects_46",
    "Objects_47",
    "Objects_48",
    "Objects_49",
    "Objects_5",
    "Objects_50",
    "Objects_51",
    "Objects_52",
    "Objects_53",
    "Objects_54",
    "Objects_55",
    "Objects_56",
    "Objects_57",
    "Objects_58",
    "Objects_59",
    "Objects_6",
    "Objects_60",
    "Objects_61",
    "Objects_62",
    "Objects_63",
    "Objects_64",
    "Objects_65",
    "Objects_66",
    "Objects_67",
    "Objects_68",
    "Objects_69",
    "Objects_7",
    "Objects_70",
    "Objects_71",
    "Objects_72",
    "Objects_73",
    "Objects_74",
    "Objects_75",
    "Objects_76",
    "Objects_77",
    "Objects_78",
    "Objects_79",
    "Objects_8",
    "Objects_80",
    "Objects_81",
    "Objects_82",
    "Objects_83",
    "Objects_84",
    "Objects_85",
    "Objects_86",
    "Objects_87",
    "Objects_88",
    "Objects_89",
    "Objects_9",
    "Objects_90",
    "Objects_91",
    "Objects_92",
    "Objects_93",
    "Objects_94",
    "Objects_95",
    "Objects_96",
    "Objects_97",
    "Objects_98",
    "Objects_99",
    "ObservabilityArizeDestination",
    "ObservabilityBraintrustDestination",
    "ObservabilityClickhouseDestination",
    "ObservabilityDatadogDestination",
    "ObservabilityDestination",
    "ObservabilityFilterRuleGroup",
    "ObservabilityFilterRulesConfig",
    "ObservabilityFilterRulesConfigNullable",
    "ObservabilityGrafanaDestination",
    "ObservabilityLangfuseDestination",
    "ObservabilityLangsmithDestination",
    "ObservabilityNewrelicDestination",
    "ObservabilityOpikDestination",
    "ObservabilityOtelCollectorDestination",
    "ObservabilityPosthogDestination",
    "ObservabilityRampDestination",
    "ObservabilityS3Destination",
    "ObservabilitySentryDestination",
    "ObservabilitySnowflakeDestination",
    "ObservabilityWeaveDestination",
    "ObservabilityWebhookDestination",
    "OpenAIResponseCustomToolCall",
    "OpenAIResponseCustomToolCallOutput",
    "OpenAIResponseFunctionToolCall",
    "OpenAIResponseFunctionToolCallOutput",
    "OpenAIResponseInputMessageItem",
    "OpenAIResponsesAnnotation",
    "OpenAIResponsesImageGenCallCompleted",
    "OpenAIResponsesImageGenCallGenerating",
    "OpenAIResponsesImageGenCallInProgress",
    "OpenAIResponsesImageGenCallPartialImage",
    "OpenAIResponsesRefusalContent",
    "OpenAIResponsesResponseStatus",
    "OpenAIResponsesSearchCompleted",
    "OpenAIResponsesToolChoice",
    "OpenAIResponsesTruncation",
    "OpenAIResponsesUsage",
    "OpenAIResponsesWebSearchCallInProgress",
    "OpenAIResponsesWebSearchCallSearching",
    "OpenResponsesCreatedEvent",
    "OpenResponsesInProgressEvent",
    "OpenResponsesLogProbs",
    "OpenResponsesResult",
    "OpenResponsesTopLogprobs",
    "OpenRouterMetadata",
    "OpenRouterWebSearchServerTool",
    "OutputAdvisorServerToolItem",
    "OutputApplyPatchCallItem",
    "OutputApplyPatchServerToolItem",
    "OutputBashServerToolItem",
    "OutputBrowserUseServerToolItem",
    "OutputCodeInterpreterCallItem",
    "OutputCodeInterpreterServerToolItem",
    "OutputComputerCallItem",
    "OutputCustomToolCallItem",
    "OutputDatetimeItem",
    "OutputFileSearchCallItem",
    "OutputFileSearchServerToolItem",
    "OutputFilesServerToolItem",
    "OutputFunctionCallItem",
    "OutputFusionServerToolItem",
    "OutputImageGenerationCallItem",
    "OutputImageGenerationServerToolItem",
    "OutputItemAddedEvent",
    "OutputItemApplyPatchCall",
    "OutputItemCustomToolCall",
    "OutputItemDoneEvent",
    "OutputItemFileSearchCall",
    "OutputItemFunctionCall",
    "OutputItemImageGenerationCall",
    "OutputItemReasoning",
    "OutputItemWebSearchCall",
    "OutputItems",
    "OutputMcpServerToolItem",
    "OutputMemoryServerToolItem",
    "OutputMessage",
    "OutputMessageItem",
    "OutputModality",
    "OutputModalityEnum",
    "OutputReasoningItem",
    "OutputSearchModelsServerToolItem",
    "OutputShellCallItem",
    "OutputShellCallOutputItem",
    "OutputSubagentServerToolItem",
    "OutputTextEditorServerToolItem",
    "OutputToolSearchServerToolItem",
    "OutputWebFetchServerToolItem",
    "OutputWebSearchCallItem",
    "OutputWebSearchServerToolItem",
    "PDFParserEngine",
    "PDFParserOptions",
    "Parameter",
    "ParetoRouterPlugin",
    "PayloadTooLargeResponse",
    "PayloadTooLargeResponseErrorData",
    "PaymentRequiredResponse",
    "PaymentRequiredResponseErrorData",
    "PerRequestLimits",
    "PercentileLatencyCutoffs",
    "PercentileStats",
    "PercentileThroughputCutoffs",
    "PipelineStage",
    "PipelineStageType",
    "Prediction",
    "PredictionContentText",
    "PreferredMaxLatency",
    "PreferredMinThroughput",
    "Preset",
    "PresetDesignatedVersion",
    "PresetStatus",
    "PresetWithDesignatedVersion",
    "Preview_20250311_WebSearchServerTool",
    "Preview_WebSearchServerTool",
    "Preview_WebSearchUserLocation",
    "PricingOverride",
    "PromptCacheBreakpoint",
    "PromptCacheOptions",
    "PromptInjectionScanScope",
    "ProviderName",
    "ProviderOptions",
    "ProviderOverloadedResponse",
    "ProviderOverloadedResponseErrorData",
    "ProviderPreferences",
    "ProviderResponse",
    "ProviderSort",
    "ProviderSortConfig",
    "PublicEndpoint",
    "PublicPricing",
    "Quantization",
    "QueryAnalytics200",
    "QueryAnalytics400",
    "QueryAnalytics401",
    "QueryAnalytics403",
    "QueryAnalytics408",
    "QueryAnalytics500",
    "QueryAnalyticsParams",
    "QueryAnalyticsRequestJson",
    "RangeCapability",
    "RankingsDailyItem",
    "RankingsDailyMeta",
    "RankingsDailyResponse",
    "ReasoningConfig",
    "ReasoningContext",
    "ReasoningDeltaEvent",
    "ReasoningDetailEncrypted",
    "ReasoningDetailServerToolCall",
    "ReasoningDetailSummary",
    "ReasoningDetailText",
    "ReasoningDetailUnion",
    "ReasoningDoneEvent",
    "ReasoningEffort",
    "ReasoningFormat",
    "ReasoningItem",
    "ReasoningMode",
    "ReasoningSummaryPartAddedEvent",
    "ReasoningSummaryPartDoneEvent",
    "ReasoningSummaryText",
    "ReasoningSummaryTextDeltaEvent",
    "ReasoningSummaryTextDoneEvent",
    "ReasoningSummaryVerbosity",
    "ReasoningTextContent",
    "RefusalDeltaEvent",
    "RefusalDoneEvent",
    "RequestMetadata",
    "RequestTimeoutResponse",
    "RequestTimeoutResponseErrorData",
    "ResponseHealingPlugin",
    "ResponseIncludesEnum",
    "ResponseOutputText",
    "ResponsesErrorField",
    "ResponsesRequest",
    "ResponsesStreamingResponse",
    "RouterAttempt",
    "RouterParams",
    "RoutingStrategy",
    "STTInputAudio",
    "STTRequest",
    "STTResponse",
    "STTSegment",
    "STTTimestampGranularity",
    "STTUsage",
    "STTWord",
    "SandboxSleepAfterSeconds",
    "SearchContextSizeEnum",
    "SearchModelsServerToolConfig",
    "SearchModelsServerTool_OpenRouter",
    "SearchQualityLevel",
    "SendChatCompletionRequest200",
    "SendChatCompletionRequest200Sse",
    "SendChatCompletionRequest400",
    "SendChatCompletionRequest401",
    "SendChatCompletionRequest402",
    "SendChatCompletionRequest403",
    "SendChatCompletionRequest404",
    "SendChatCompletionRequest408",
    "SendChatCompletionRequest413",
    "SendChatCompletionRequest422",
    "SendChatCompletionRequest429",
    "SendChatCompletionRequest500",
    "SendChatCompletionRequest502",
    "SendChatCompletionRequest503",
    "SendChatCompletionRequest524",
    "SendChatCompletionRequest529",
    "SendChatCompletionRequestParams",
    "SendChatCompletionRequestRequestJson",
    "ServerToolUseDetails",
    "ServiceTier",
    "ServiceUnavailableResponse",
    "ServiceUnavailableResponseErrorData",
    "ShellCallItem",
    "ShellCallOutputItem",
    "ShellCallStatus",
    "ShellServerTool",
    "ShellServerToolConfig",
    "ShellServerToolEngine",
    "ShellServerToolEnvironment",
    "ShellServerTool_OpenRouter",
    "SpeechRequest",
    "StopServerToolsWhen",
    "StopServerToolsWhenCondition",
    "StopServerToolsWhenFinishReasonIs",
    "StopServerToolsWhenHasToolCall",
    "StopServerToolsWhenMaxCost",
    "StopServerToolsWhenMaxTokensUsed",
    "StopServerToolsWhenStepCountIs",
    "StoredPromptTemplate",
    "StreamEvents",
    "StreamEventsResponseCompleted",
    "StreamEventsResponseFailed",
    "StreamEventsResponseIncomplete",
    "StreamEventsResponseOutputItemAdded",
    "StreamEventsResponseOutputItemDone",
    "StreamLogprob",
    "StreamLogprobTopLogprob",
    "SubagentNestedTool",
    "SubagentReasoning",
    "SubagentServerToolConfig",
    "SubagentServerTool_OpenRouter",
    "SubmitGenerationFeedback200",
    "SubmitGenerationFeedback400",
    "SubmitGenerationFeedback401",
    "SubmitGenerationFeedback404",
    "SubmitGenerationFeedback429",
    "SubmitGenerationFeedback500",
    "SubmitGenerationFeedbackParams",
    "SubmitGenerationFeedbackRequest",
    "SubmitGenerationFeedbackRequestJson",
    "SubmitGenerationFeedbackResponse",
    "SupportedParameters",
    "TaskClassificationItem",
    "TaskClassificationMacroCategory",
    "TaskClassificationModel",
    "TaskClassificationResponse",
    "TextConfig",
    "TextDeltaEvent",
    "TextDoneEvent",
    "TextExtendedConfig",
    "TooManyRequestsResponse",
    "TooManyRequestsResponseErrorData",
    "ToolCallStatus",
    "ToolChoiceAllowed",
    "TopProviderInfo",
    "TraceConfig",
    "Truncation",
    "URLCitation",
    "UnauthorizedResponse",
    "UnauthorizedResponseErrorData",
    "UnifiedBenchmarkPricing",
    "UnifiedBenchmarksAAItem",
    "UnifiedBenchmarksDAItem",
    "UnifiedBenchmarksMeta",
    "UnifiedBenchmarksResponse",
    "Union_",
    "Union_1",
    "Union_10",
    "Union_11",
    "Union_12",
    "Union_13",
    "Union_2",
    "Union_3",
    "Union_4",
    "Union_5",
    "Union_6",
    "Union_7",
    "Union_8",
    "Union_9",
    "UnprocessableEntityResponse",
    "UnprocessableEntityResponseErrorData",
    "UpdateBYOKKey200",
    "UpdateBYOKKey400",
    "UpdateBYOKKey401",
    "UpdateBYOKKey404",
    "UpdateBYOKKey500",
    "UpdateBYOKKeyParams",
    "UpdateBYOKKeyRequest",
    "UpdateBYOKKeyRequestJson",
    "UpdateBYOKKeyResponse",
    "UpdateGuardrail200",
    "UpdateGuardrail400",
    "UpdateGuardrail401",
    "UpdateGuardrail404",
    "UpdateGuardrail500",
    "UpdateGuardrailParams",
    "UpdateGuardrailRequest",
    "UpdateGuardrailRequestJson",
    "UpdateGuardrailResponse",
    "UpdateKeys200",
    "UpdateKeys400",
    "UpdateKeys401",
    "UpdateKeys404",
    "UpdateKeys429",
    "UpdateKeys500",
    "UpdateKeysParams",
    "UpdateKeysRequestJson",
    "UpdateObservabilityDestination200",
    "UpdateObservabilityDestination400",
    "UpdateObservabilityDestination401",
    "UpdateObservabilityDestination404",
    "UpdateObservabilityDestination409",
    "UpdateObservabilityDestination500",
    "UpdateObservabilityDestinationParams",
    "UpdateObservabilityDestinationRequest",
    "UpdateObservabilityDestinationRequestJson",
    "UpdateObservabilityDestinationResponse",
    "UpdateWorkspace200",
    "UpdateWorkspace400",
    "UpdateWorkspace401",
    "UpdateWorkspace403",
    "UpdateWorkspace404",
    "UpdateWorkspace500",
    "UpdateWorkspaceParams",
    "UpdateWorkspaceRequest",
    "UpdateWorkspaceRequestJson",
    "UpdateWorkspaceResponse",
    "UploadFile200",
    "UploadFile400",
    "UploadFile401",
    "UploadFile403",
    "UploadFile413",
    "UploadFile429",
    "UploadFile500",
    "UploadFileParams",
    "UploadFileRequestFormData",
    "UpsertWorkspaceBudget200",
    "UpsertWorkspaceBudget400",
    "UpsertWorkspaceBudget401",
    "UpsertWorkspaceBudget404",
    "UpsertWorkspaceBudget500",
    "UpsertWorkspaceBudgetParams",
    "UpsertWorkspaceBudgetRequest",
    "UpsertWorkspaceBudgetRequestJson",
    "UpsertWorkspaceBudgetResponse",
    "Usage",
    "VideoGenerationRequest",
    "VideoGenerationResponse",
    "VideoGenerationUsage",
    "VideoModel",
    "VideoModelsListResponse",
    "WebFetchEngineEnum",
    "WebFetchPlugin",
    "WebFetchServerTool",
    "WebFetchServerToolConfig",
    "WebSearchCallCompletedEvent",
    "WebSearchCallInProgressEvent",
    "WebSearchCallSearchingEvent",
    "WebSearchConfig",
    "WebSearchDomainFilter",
    "WebSearchEngine",
    "WebSearchEngineEnum",
    "WebSearchPlugin",
    "WebSearchServerTool",
    "WebSearchServerToolConfig",
    "WebSearchServerTool_OpenRouter",
    "WebSearchSource",
    "WebSearchStatus",
    "WebSearchUserLocation",
    "WebSearchUserLocationServerTool",
    "Workspace",
    "WorkspaceBudget",
    "WorkspaceBudgetInterval",
    "WorkspaceMember",
]
