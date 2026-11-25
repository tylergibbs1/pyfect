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

from pyfect.ai.openrouter.generated._schemas_0 import ActivityItem as ActivityItem
from pyfect.ai.openrouter.generated._schemas_0 import ActivityResponse as ActivityResponse
from pyfect.ai.openrouter.generated._schemas_0 import BadRequestResponseErrorData as BadRequestResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import BadRequestResponse as BadRequestResponse
from pyfect.ai.openrouter.generated._schemas_0 import UnauthorizedResponseErrorData as UnauthorizedResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import UnauthorizedResponse as UnauthorizedResponse
from pyfect.ai.openrouter.generated._schemas_0 import ForbiddenResponseErrorData as ForbiddenResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ForbiddenResponse as ForbiddenResponse
from pyfect.ai.openrouter.generated._schemas_0 import NotFoundResponseErrorData as NotFoundResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import NotFoundResponse as NotFoundResponse
from pyfect.ai.openrouter.generated._schemas_0 import InternalServerResponseErrorData as InternalServerResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import InternalServerResponse as InternalServerResponse
from pyfect.ai.openrouter.generated._schemas_0 import Operator as Operator
from pyfect.ai.openrouter.generated._schemas_0 import ClassifierScalarFilterOperator as ClassifierScalarFilterOperator
from pyfect.ai.openrouter.generated._schemas_0 import ClassifierScalarFilter as ClassifierScalarFilter
from pyfect.ai.openrouter.generated._schemas_0 import ClassifierSetFilterOperator as ClassifierSetFilterOperator
from pyfect.ai.openrouter.generated._schemas_0 import ClassifierSetFilter as ClassifierSetFilter
from pyfect.ai.openrouter.generated._schemas_0 import ClassifierFiltersFilter as ClassifierFiltersFilter
from pyfect.ai.openrouter.generated._schemas_0 import ScalarFilterOperator as ScalarFilterOperator
from pyfect.ai.openrouter.generated._schemas_0 import ScalarFilter as ScalarFilter
from pyfect.ai.openrouter.generated._schemas_0 import SetFilterOperator as SetFilterOperator
from pyfect.ai.openrouter.generated._schemas_0 import SetFilter as SetFilter
from pyfect.ai.openrouter.generated._schemas_0 import Filter as Filter
from pyfect.ai.openrouter.generated._schemas_0 import RequestTimeoutResponseErrorData as RequestTimeoutResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import RequestTimeoutResponse as RequestTimeoutResponse
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsImageAsset as DecisionsImageAsset
from pyfect.ai.openrouter.generated._schemas_0 import ProviderName as ProviderName
from pyfect.ai.openrouter.generated._schemas_0 import ProviderOptions as ProviderOptions
from pyfect.ai.openrouter.generated._schemas_0 import PercentileLatencyCutoffs as PercentileLatencyCutoffs
from pyfect.ai.openrouter.generated._schemas_0 import PreferredMaxLatency as PreferredMaxLatency
from pyfect.ai.openrouter.generated._schemas_0 import PercentileThroughputCutoffs as PercentileThroughputCutoffs
from pyfect.ai.openrouter.generated._schemas_0 import PreferredMinThroughput as PreferredMinThroughput
from pyfect.ai.openrouter.generated._schemas_0 import Quantization as Quantization
from pyfect.ai.openrouter.generated._schemas_0 import ProviderSort as ProviderSort
from pyfect.ai.openrouter.generated._schemas_0 import ProviderSortConfig as ProviderSortConfig
from pyfect.ai.openrouter.generated._schemas_0 import ProviderPreferences as ProviderPreferences
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsNoulQuestion as DecisionsNoulQuestion
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsChoiceQuestion as DecisionsChoiceQuestion
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsScoreQuestion as DecisionsScoreQuestion
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsBoxQuestion as DecisionsBoxQuestion
from pyfect.ai.openrouter.generated._schemas_0 import TraceConfig as TraceConfig
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsRequest as DecisionsRequest
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsUrlCitationAnnotation as DecisionsUrlCitationAnnotation
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsNoulAnswer as DecisionsNoulAnswer
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsChoiceAnswer as DecisionsChoiceAnswer
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsScoreAnswer as DecisionsScoreAnswer
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsBoxAnswer as DecisionsBoxAnswer
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsRefusalAnswer as DecisionsRefusalAnswer
from pyfect.ai.openrouter.generated._schemas_0 import CostDetails as CostDetails
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsUsageInputTokensDetails as DecisionsUsageInputTokensDetails
from pyfect.ai.openrouter.generated._schemas_0 import DecisionsResponse as DecisionsResponse
from pyfect.ai.openrouter.generated._schemas_0 import PaymentRequiredResponseErrorData as PaymentRequiredResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import PaymentRequiredResponse as PaymentRequiredResponse
from pyfect.ai.openrouter.generated._schemas_0 import PayloadTooLargeResponseErrorData as PayloadTooLargeResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import PayloadTooLargeResponse as PayloadTooLargeResponse
from pyfect.ai.openrouter.generated._schemas_0 import TooManyRequestsResponseErrorData as TooManyRequestsResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import TooManyRequestsResponse as TooManyRequestsResponse
from pyfect.ai.openrouter.generated._schemas_0 import BadGatewayResponseErrorData as BadGatewayResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import BadGatewayResponse as BadGatewayResponse
from pyfect.ai.openrouter.generated._schemas_0 import ServiceUnavailableResponseErrorData as ServiceUnavailableResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ServiceUnavailableResponse as ServiceUnavailableResponse
from pyfect.ai.openrouter.generated._schemas_0 import EdgeNetworkTimeoutResponseErrorData as EdgeNetworkTimeoutResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import EdgeNetworkTimeoutResponse as EdgeNetworkTimeoutResponse
from pyfect.ai.openrouter.generated._schemas_0 import ProviderOverloadedResponseErrorData as ProviderOverloadedResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ProviderOverloadedResponse as ProviderOverloadedResponse
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionAsset as ExtractionAsset
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionTextField as ExtractionTextField
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionNumberField as ExtractionNumberField
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionDateField as ExtractionDateField
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionTimeField as ExtractionTimeField
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionDatetimeField as ExtractionDatetimeField
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionDurationField as ExtractionDurationField
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionListField as ExtractionListField
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionEstimateField as ExtractionEstimateField
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionForecastField as ExtractionForecastField
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionsRequest as ExtractionsRequest
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionTextAnswer as ExtractionTextAnswer
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionNumberAnswer as ExtractionNumberAnswer
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionDateAnswer as ExtractionDateAnswer
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionTimeAnswer as ExtractionTimeAnswer
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionDatetimeAnswer as ExtractionDatetimeAnswer
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionDurationAnswer as ExtractionDurationAnswer
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionListAnswer as ExtractionListAnswer
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionEstimateAnswer as ExtractionEstimateAnswer
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionForecastStep as ExtractionForecastStep
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionForecastAnswer as ExtractionForecastAnswer
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionsUsage as ExtractionsUsage
from pyfect.ai.openrouter.generated._schemas_0 import ExtractionsResponse as ExtractionsResponse
from pyfect.ai.openrouter.generated._schemas_0 import SpeechTurn as SpeechTurn
from pyfect.ai.openrouter.generated._schemas_0 import SpeechInput as SpeechInput
from pyfect.ai.openrouter.generated._schemas_0 import SpeechInputReferenceAudioInput as SpeechInputReferenceAudioInput
from pyfect.ai.openrouter.generated._schemas_0 import SpeechInputReferenceAudio as SpeechInputReferenceAudio
from pyfect.ai.openrouter.generated._schemas_0 import SpeechInputReferenceText as SpeechInputReferenceText
from pyfect.ai.openrouter.generated._schemas_0 import SpeechInputReferenceImageInput as SpeechInputReferenceImageInput
from pyfect.ai.openrouter.generated._schemas_0 import SpeechInputReferenceImage as SpeechInputReferenceImage
from pyfect.ai.openrouter.generated._schemas_0 import SpeechInputReference as SpeechInputReference
from pyfect.ai.openrouter.generated._schemas_0 import SpeechRequest as SpeechRequest
from pyfect.ai.openrouter.generated._schemas_0 import STTInlineInputAudio as STTInlineInputAudio
from pyfect.ai.openrouter.generated._schemas_0 import STTUrlInputAudio as STTUrlInputAudio
from pyfect.ai.openrouter.generated._schemas_0 import STTInputAudio as STTInputAudio
from pyfect.ai.openrouter.generated._schemas_0 import STTTimestampGranularity as STTTimestampGranularity
from pyfect.ai.openrouter.generated._schemas_0 import STTRequest as STTRequest
from pyfect.ai.openrouter.generated._schemas_0 import STTEntity as STTEntity
from pyfect.ai.openrouter.generated._schemas_0 import STTSegment as STTSegment
from pyfect.ai.openrouter.generated._schemas_0 import STTUsage as STTUsage
from pyfect.ai.openrouter.generated._schemas_0 import STTWord as STTWord
from pyfect.ai.openrouter.generated._schemas_0 import STTResponse as STTResponse
from pyfect.ai.openrouter.generated._schemas_0 import GatewayTimeoutResponseErrorData as GatewayTimeoutResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import GatewayTimeoutResponse as GatewayTimeoutResponse
from pyfect.ai.openrouter.generated._schemas_0 import ConflictResponseErrorData as ConflictResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ConflictResponse as ConflictResponse
from pyfect.ai.openrouter.generated._schemas_0 import BatchListStatus as BatchListStatus
from pyfect.ai.openrouter.generated._schemas_0 import BatchListTimestamp as BatchListTimestamp
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCacheCreation as AnthropicCacheCreation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicIterationCacheCreation as AnthropicIterationCacheCreation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCompactionUsageIteration as AnthropicCompactionUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicMessageUsageIteration as AnthropicMessageUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicAdvisorMessageUsageIteration as AnthropicAdvisorMessageUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicUnknownUsageIteration as AnthropicUnknownUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicUsageIteration as AnthropicUsageIteration
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicSpeed as AnthropicSpeed
from pyfect.ai.openrouter.generated._schemas_0 import BatchListItem as BatchListItem
from pyfect.ai.openrouter.generated._schemas_0 import BatchListResponse as BatchListResponse
from pyfect.ai.openrouter.generated._schemas_0 import BatchErrorResponse as BatchErrorResponse
from pyfect.ai.openrouter.generated._schemas_0 import BatchProviderPreferences as BatchProviderPreferences
from pyfect.ai.openrouter.generated._schemas_0 import BatchSubmitBody as BatchSubmitBody
from pyfect.ai.openrouter.generated._schemas_0 import ApiErrorType as ApiErrorType
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentRuleRecord as AlignmentRuleRecord
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentAllowedCallRecord as AlignmentAllowedCallRecord
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentBlockedCallRecord as AlignmentBlockedCallRecord
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentUnavailableCallRecord as AlignmentUnavailableCallRecord
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentCallRecord as AlignmentCallRecord
from pyfect.ai.openrouter.generated._schemas_0 import Alignment as Alignment
from pyfect.ai.openrouter.generated._schemas_0 import FinishReason as FinishReason
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningFormat as ReasoningFormat
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDetailSummary as ReasoningDetailSummary
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDetailEncrypted as ReasoningDetailEncrypted
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDetailText as ReasoningDetailText
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDetailServerToolCall as ReasoningDetailServerToolCall
from pyfect.ai.openrouter.generated._schemas_0 import RouterAttempt as RouterAttempt
from pyfect.ai.openrouter.generated._schemas_0 import EndpointInfo as EndpointInfo
from pyfect.ai.openrouter.generated._schemas_0 import EndpointsMetadata as EndpointsMetadata
from pyfect.ai.openrouter.generated._schemas_0 import RouterParams as RouterParams
from pyfect.ai.openrouter.generated._schemas_0 import PipelineStageType as PipelineStageType
from pyfect.ai.openrouter.generated._schemas_0 import PipelineStage as PipelineStage
from pyfect.ai.openrouter.generated._schemas_0 import RoutingStrategy as RoutingStrategy
from pyfect.ai.openrouter.generated._schemas_0 import OpenRouterMetadata as OpenRouterMetadata
from pyfect.ai.openrouter.generated._schemas_0 import ArmorSafeguardResult as ArmorSafeguardResult
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentChatAudio as AlignmentChatAudio
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentChatImage as AlignmentChatImage
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentChatToolCall as AlignmentChatToolCall
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentChatRejected as AlignmentChatRejected
from pyfect.ai.openrouter.generated._schemas_0 import FileCitation as FileCitation
from pyfect.ai.openrouter.generated._schemas_0 import URLCitation as URLCitation
from pyfect.ai.openrouter.generated._schemas_0 import FilePath as FilePath
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesAnnotation as OpenAIResponsesAnnotation
from pyfect.ai.openrouter.generated._schemas_0 import ResponseOutputText as ResponseOutputText
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesRefusalContent as OpenAIResponsesRefusalContent
from pyfect.ai.openrouter.generated._schemas_0 import OutputMessage as OutputMessage
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningTextContent as ReasoningTextContent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryText as ReasoningSummaryText
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemReasoning as OutputItemReasoning
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemFunctionCall as OutputItemFunctionCall
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemCustomToolCall as OutputItemCustomToolCall
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchSource as WebSearchSource
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchStatus as WebSearchStatus
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemWebSearchCall as OutputItemWebSearchCall
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemFileSearchCall as OutputItemFileSearchCall
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationStatus as ImageGenerationStatus
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemImageGenerationCall as OutputItemImageGenerationCall
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCreateFileOperation as ApplyPatchCreateFileOperation
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchUpdateFileOperation as ApplyPatchUpdateFileOperation
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchDeleteFileOperation as ApplyPatchDeleteFileOperation
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemApplyPatchCall as OutputItemApplyPatchCall
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterLogsOutput as CodeInterpreterLogsOutput
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterImageOutput as CodeInterpreterImageOutput
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterFileOutput as CodeInterpreterFileOutput
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemCodeInterpreterCall as OutputItemCodeInterpreterCall
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemCompaction as OutputItemCompaction
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemMcpListTools as OutputItemMcpListTools
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemMcpCall as OutputItemMcpCall
from pyfect.ai.openrouter.generated._schemas_0 import OutputItemMcpApprovalRequest as OutputItemMcpApprovalRequest
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentResponsesRejected as AlignmentResponsesRejected
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentRejected as AlignmentRejected
from pyfect.ai.openrouter.generated._schemas_0 import OpenResponsesErrorMetadata as OpenResponsesErrorMetadata
from pyfect.ai.openrouter.generated._schemas_0 import IncompleteDetails as IncompleteDetails
from pyfect.ai.openrouter.generated._schemas_0 import PromptCacheBreakpoint as PromptCacheBreakpoint
from pyfect.ai.openrouter.generated._schemas_0 import InputText as InputText
from pyfect.ai.openrouter.generated._schemas_0 import InputImage as InputImage
from pyfect.ai.openrouter.generated._schemas_0 import InputFile as InputFile
from pyfect.ai.openrouter.generated._schemas_0 import InputAudio as InputAudio
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponseInputMessageItem as OpenAIResponseInputMessageItem
from pyfect.ai.openrouter.generated._schemas_0 import ToolCallStatus as ToolCallStatus
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponseFunctionToolCallOutput as OpenAIResponseFunctionToolCallOutput
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponseFunctionToolCall as OpenAIResponseFunctionToolCall
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponseCustomToolCall as OpenAIResponseCustomToolCall
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponseCustomToolCallOutput as OpenAIResponseCustomToolCallOutput
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallOperation as ApplyPatchCallOperation
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallStatus as ApplyPatchCallStatus
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallItem as ApplyPatchCallItem
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallOutputItem as ApplyPatchCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import ConfigurationUpdateReasoning as ConfigurationUpdateReasoning
from pyfect.ai.openrouter.generated._schemas_0 import ConfigurationUpdateItem as ConfigurationUpdateItem
from pyfect.ai.openrouter.generated._schemas_0 import BaseInputs as BaseInputs
from pyfect.ai.openrouter.generated._schemas_0 import RequestMetadata as RequestMetadata
from pyfect.ai.openrouter.generated._schemas_0 import StoredPromptTemplate as StoredPromptTemplate
from pyfect.ai.openrouter.generated._schemas_0 import PromptCacheOptions as PromptCacheOptions
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningContext as ReasoningContext
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningEffort as ReasoningEffort
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningMode as ReasoningMode
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryVerbosity as ReasoningSummaryVerbosity
from pyfect.ai.openrouter.generated._schemas_0 import BaseReasoningConfig as BaseReasoningConfig
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesResponseStatus as OpenAIResponsesResponseStatus
from pyfect.ai.openrouter.generated._schemas_0 import FormatTextConfig as FormatTextConfig
from pyfect.ai.openrouter.generated._schemas_0 import FormatJsonObjectConfig as FormatJsonObjectConfig
from pyfect.ai.openrouter.generated._schemas_0 import FormatJsonSchemaConfig as FormatJsonSchemaConfig
from pyfect.ai.openrouter.generated._schemas_0 import Formats as Formats
from pyfect.ai.openrouter.generated._schemas_0 import ToolChoiceAllowed as ToolChoiceAllowed
from pyfect.ai.openrouter.generated._schemas_0 import ToolChoiceMcp as ToolChoiceMcp
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesToolChoice as OpenAIResponsesToolChoice
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchEngineEnum as WebSearchEngineEnum
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchDomainFilter as WebSearchDomainFilter
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchMode as WebSearchMode
from pyfect.ai.openrouter.generated._schemas_0 import SearchContextSizeEnum as SearchContextSizeEnum
from pyfect.ai.openrouter.generated._schemas_0 import Preview_WebSearchUserLocation as Preview_WebSearchUserLocation
from pyfect.ai.openrouter.generated._schemas_0 import XSearchOptions as XSearchOptions
from pyfect.ai.openrouter.generated._schemas_0 import Preview_WebSearchServerTool as Preview_WebSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import Preview_20250311_WebSearchServerTool as Preview_20250311_WebSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchUserLocation as WebSearchUserLocation
from pyfect.ai.openrouter.generated._schemas_0 import Legacy_WebSearchServerTool as Legacy_WebSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchServerTool as WebSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import CompoundFilter as CompoundFilter
from pyfect.ai.openrouter.generated._schemas_0 import FileSearchServerTool as FileSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ComputerUseServerTool as ComputerUseServerTool
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterServerTool as CodeInterpreterServerTool
from pyfect.ai.openrouter.generated._schemas_0 import McpServerTool as McpServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationServerTool as ImageGenerationServerTool
from pyfect.ai.openrouter.generated._schemas_0 import CodexLocalShellTool as CodexLocalShellTool
from pyfect.ai.openrouter.generated._schemas_0 import ShellServerTool as ShellServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchServerTool as ApplyPatchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import CustomTool as CustomTool
from pyfect.ai.openrouter.generated._schemas_0 import NamespaceFunctionTool as NamespaceFunctionTool
from pyfect.ai.openrouter.generated._schemas_0 import NamespaceTool as NamespaceTool
from pyfect.ai.openrouter.generated._schemas_0 import Truncation as Truncation
from pyfect.ai.openrouter.generated._schemas_0 import DeferredToolsDetails as DeferredToolsDetails
from pyfect.ai.openrouter.generated._schemas_0 import ServerToolUseDetails as ServerToolUseDetails
from pyfect.ai.openrouter.generated._schemas_0 import OpenResponsesResult as OpenResponsesResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicContainerSkill as AnthropicContainerSkill
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicContainer as AnthropicContainer
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationCharLocation as AnthropicCitationCharLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationPageLocation as AnthropicCitationPageLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationContentBlockLocation as AnthropicCitationContentBlockLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationWebSearchResultLocation as AnthropicCitationWebSearchResultLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationSearchResultLocation as AnthropicCitationSearchResultLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextCitation as AnthropicTextCitation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextBlock as AnthropicTextBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicDirectCaller as AnthropicDirectCaller
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecution20250825Caller as AnthropicCodeExecution20250825Caller
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecution20260120Caller as AnthropicCodeExecution20260120Caller
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCaller as AnthropicCaller
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolUseBlock as AnthropicToolUseBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicThinkingBlock as AnthropicThinkingBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicRedactedThinkingBlock as AnthropicRedactedThinkingBlock
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicNullableCaller as ORAnthropicNullableCaller
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicServerToolUseBlock as ORAnthropicServerToolUseBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebSearchResult as AnthropicWebSearchResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebSearchToolResultError as AnthropicWebSearchToolResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebSearchToolResult as AnthropicWebSearchToolResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebFetchToolResultError as AnthropicWebFetchToolResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationsConfig as AnthropicCitationsConfig
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBase64PdfSource as AnthropicBase64PdfSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicPlainTextSource as AnthropicPlainTextSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicDocumentBlock as AnthropicDocumentBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebFetchBlock as AnthropicWebFetchBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebFetchContent as AnthropicWebFetchContent
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebFetchToolResult as AnthropicWebFetchToolResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicServerToolErrorCode as AnthropicServerToolErrorCode
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecutionToolResultError as AnthropicCodeExecutionToolResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecutionOutput as AnthropicCodeExecutionOutput
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecutionResult as AnthropicCodeExecutionResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicEncryptedCodeExecutionResult as AnthropicEncryptedCodeExecutionResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecutionContent as AnthropicCodeExecutionContent
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCodeExecutionToolResult as AnthropicCodeExecutionToolResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBashCodeExecutionToolResultError as AnthropicBashCodeExecutionToolResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBashCodeExecutionOutput as AnthropicBashCodeExecutionOutput
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBashCodeExecutionResult as AnthropicBashCodeExecutionResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBashCodeExecutionContent as AnthropicBashCodeExecutionContent
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBashCodeExecutionToolResult as AnthropicBashCodeExecutionToolResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionToolResultError as AnthropicTextEditorCodeExecutionToolResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionViewResult as AnthropicTextEditorCodeExecutionViewResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionCreateResult as AnthropicTextEditorCodeExecutionCreateResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionStrReplaceResult as AnthropicTextEditorCodeExecutionStrReplaceResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionContent as AnthropicTextEditorCodeExecutionContent
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextEditorCodeExecutionToolResult as AnthropicTextEditorCodeExecutionToolResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchResultError as AnthropicToolSearchResultError
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolReference as AnthropicToolReference
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchResult as AnthropicToolSearchResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchContent as AnthropicToolSearchContent
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchToolResult as AnthropicToolSearchToolResult
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicContainerUpload as AnthropicContainerUpload
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCompactionBlock as AnthropicCompactionBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicAdvisorToolResult as AnthropicAdvisorToolResult
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicShellToolResult as ORAnthropicShellToolResult
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicBashToolResult as ORAnthropicBashToolResult
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicToolSearchResult as ORAnthropicToolSearchResult
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicContentBlock as ORAnthropicContentBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicInputTransformation as AnthropicInputTransformation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicRefusalStopDetails as AnthropicRefusalStopDetails
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicStopReason as ORAnthropicStopReason
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicOutputTokensDetails as AnthropicOutputTokensDetails
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicServerToolUsage as AnthropicServerToolUsage
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicServiceTier as AnthropicServiceTier
from pyfect.ai.openrouter.generated._schemas_0 import BatchObject as BatchObject
from pyfect.ai.openrouter.generated._schemas_0 import BatchPaymentRequiredResponse as BatchPaymentRequiredResponse
from pyfect.ai.openrouter.generated._schemas_0 import BatchDeletionOutcome as BatchDeletionOutcome
from pyfect.ai.openrouter.generated._schemas_0 import BatchDeletionTargets as BatchDeletionTargets
from pyfect.ai.openrouter.generated._schemas_0 import BatchDeletedObject as BatchDeletedObject
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarkPricing as UnifiedBenchmarkPricing
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksAAItem as UnifiedBenchmarksAAItem
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksDAItem as UnifiedBenchmarksDAItem
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksORItem as UnifiedBenchmarksORItem
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksSearchRunConfig as UnifiedBenchmarksSearchRunConfig
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksSearchItem as UnifiedBenchmarksSearchItem
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksMeta as UnifiedBenchmarksMeta
from pyfect.ai.openrouter.generated._schemas_0 import UnifiedBenchmarksResponse as UnifiedBenchmarksResponse
from pyfect.ai.openrouter.generated._schemas_0 import BYOKProviderSlug as BYOKProviderSlug
from pyfect.ai.openrouter.generated._schemas_0 import BYOKKey as BYOKKey
from pyfect.ai.openrouter.generated._schemas_0 import ListBYOKKeysResponse as ListBYOKKeysResponse
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKeyRequest as CreateBYOKKeyRequest
from pyfect.ai.openrouter.generated._schemas_0 import CreateBYOKKeyResponse as CreateBYOKKeyResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetBYOKKeyResponse as GetBYOKKeyResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteBYOKKeyResponse as DeleteBYOKKeyResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKeyRequest as UpdateBYOKKeyRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBYOKKeyResponse as UpdateBYOKKeyResponse
from pyfect.ai.openrouter.generated._schemas_0 import MetadataLevel as MetadataLevel
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCacheControlTtl as AnthropicCacheControlTtl
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCacheControlDirective as AnthropicCacheControlDirective
from pyfect.ai.openrouter.generated._schemas_0 import ChatDebugOptions as ChatDebugOptions
from pyfect.ai.openrouter.generated._schemas_0 import DeferredRegexSearch as DeferredRegexSearch
from pyfect.ai.openrouter.generated._schemas_0 import DeferredBm25Search as DeferredBm25Search
from pyfect.ai.openrouter.generated._schemas_0 import DeferredCustomSearch as DeferredCustomSearch
from pyfect.ai.openrouter.generated._schemas_0 import DeferredToolsSearchStrategy as DeferredToolsSearchStrategy
from pyfect.ai.openrouter.generated._schemas_0 import DeferredToolsControl as DeferredToolsControl
from pyfect.ai.openrouter.generated._schemas_0 import ImageConfig as ImageConfig
from pyfect.ai.openrouter.generated._schemas_0 import ConfigurationUpdate as ConfigurationUpdate
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentCacheControl as ChatContentCacheControl
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentText as ChatContentText
from pyfect.ai.openrouter.generated._schemas_0 import ChatSystemMessage as ChatSystemMessage
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentImage as ChatContentImage
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentAudio as ChatContentAudio
from pyfect.ai.openrouter.generated._schemas_0 import Legacy_ChatContentVideoInput as Legacy_ChatContentVideoInput
from pyfect.ai.openrouter.generated._schemas_0 import Legacy_ChatContentVideo as Legacy_ChatContentVideo
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentVideoInput as ChatContentVideoInput
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentVideo as ChatContentVideo
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentFile as ChatContentFile
from pyfect.ai.openrouter.generated._schemas_0 import ChatContentItems as ChatContentItems
from pyfect.ai.openrouter.generated._schemas_0 import ChatUserMessage as ChatUserMessage
from pyfect.ai.openrouter.generated._schemas_0 import ChatDeveloperMessage as ChatDeveloperMessage
from pyfect.ai.openrouter.generated._schemas_0 import ChatAudioOutput as ChatAudioOutput
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDetailUnion as ReasoningDetailUnion
from pyfect.ai.openrouter.generated._schemas_0 import ChatReasoningDetails as ChatReasoningDetails
from pyfect.ai.openrouter.generated._schemas_0 import ChatToolCall as ChatToolCall
from pyfect.ai.openrouter.generated._schemas_0 import ChatAssistantMessage as ChatAssistantMessage
from pyfect.ai.openrouter.generated._schemas_0 import ChatToolMessage as ChatToolMessage
from pyfect.ai.openrouter.generated._schemas_0 import ChatMessages as ChatMessages
from pyfect.ai.openrouter.generated._schemas_0 import ModelName as ModelName
from pyfect.ai.openrouter.generated._schemas_0 import ChatModelNames as ChatModelNames
from pyfect.ai.openrouter.generated._schemas_0 import AutoRouterPlugin as AutoRouterPlugin
from pyfect.ai.openrouter.generated._schemas_0 import AutoBetaRouterPlugin as AutoBetaRouterPlugin
from pyfect.ai.openrouter.generated._schemas_0 import ModerationPlugin as ModerationPlugin
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchEngine as WebSearchEngine
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchPlugin as WebSearchPlugin
from pyfect.ai.openrouter.generated._schemas_0 import WebFetchPlugin as WebFetchPlugin
from pyfect.ai.openrouter.generated._schemas_0 import PDFParserEngine as PDFParserEngine
from pyfect.ai.openrouter.generated._schemas_0 import PDFParserOptions as PDFParserOptions
from pyfect.ai.openrouter.generated._schemas_0 import FileParserPlugin as FileParserPlugin
from pyfect.ai.openrouter.generated._schemas_0 import ResponseHealingPlugin as ResponseHealingPlugin
from pyfect.ai.openrouter.generated._schemas_0 import ContextCompressionEngine as ContextCompressionEngine
from pyfect.ai.openrouter.generated._schemas_0 import ContextCompressionPlugin as ContextCompressionPlugin
from pyfect.ai.openrouter.generated._schemas_0 import ParetoRouterPlugin as ParetoRouterPlugin
from pyfect.ai.openrouter.generated._schemas_0 import FusionPlugin as FusionPlugin
from pyfect.ai.openrouter.generated._schemas_0 import SwitchyardRouterPlugin as SwitchyardRouterPlugin
from pyfect.ai.openrouter.generated._schemas_0 import JevRouterPlugin as JevRouterPlugin
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentRule as AlignmentRule
from pyfect.ai.openrouter.generated._schemas_0 import AlignmentPlugin as AlignmentPlugin
from pyfect.ai.openrouter.generated._schemas_0 import ArmorRule as ArmorRule
from pyfect.ai.openrouter.generated._schemas_0 import ArmorEnvironmentEntry as ArmorEnvironmentEntry
from pyfect.ai.openrouter.generated._schemas_0 import ArmorAutoMode as ArmorAutoMode
from pyfect.ai.openrouter.generated._schemas_0 import ArmorContext as ArmorContext
from pyfect.ai.openrouter.generated._schemas_0 import ArmorPlugin as ArmorPlugin
from pyfect.ai.openrouter.generated._schemas_0 import PredictionContentText as PredictionContentText
from pyfect.ai.openrouter.generated._schemas_0 import Prediction as Prediction
from pyfect.ai.openrouter.generated._schemas_0 import ChatReasoningSummaryVerbosityEnum as ChatReasoningSummaryVerbosityEnum
from pyfect.ai.openrouter.generated._schemas_0 import ChatFormatTextConfig as ChatFormatTextConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatFormatJsonObjectConfig as ChatFormatJsonObjectConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatJsonSchemaConfig as ChatJsonSchemaConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatFormatJsonSchemaConfig as ChatFormatJsonSchemaConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatFormatGrammarConfig as ChatFormatGrammarConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatFormatPythonConfig as ChatFormatPythonConfig
from pyfect.ai.openrouter.generated._schemas_0 import DeprecatedRoute as DeprecatedRoute
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenStepCountIs as StopServerToolsWhenStepCountIs
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenHasToolCall as StopServerToolsWhenHasToolCall
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenMaxTokensUsed as StopServerToolsWhenMaxTokensUsed
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenMaxCost as StopServerToolsWhenMaxCost
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenFinishReasonIs as StopServerToolsWhenFinishReasonIs
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhenCondition as StopServerToolsWhenCondition
from pyfect.ai.openrouter.generated._schemas_0 import StopServerToolsWhen as StopServerToolsWhen
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamOptions as ChatStreamOptions
from pyfect.ai.openrouter.generated._schemas_0 import ChatNamedToolChoice as ChatNamedToolChoice
from pyfect.ai.openrouter.generated._schemas_0 import ChatServerToolChoice as ChatServerToolChoice
from pyfect.ai.openrouter.generated._schemas_0 import ChatToolChoice as ChatToolChoice
from pyfect.ai.openrouter.generated._schemas_0 import AdvisorReasoning as AdvisorReasoning
from pyfect.ai.openrouter.generated._schemas_0 import AdvisorServerToolConfig as AdvisorServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import AdvisorServerTool_OpenRouter as AdvisorServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import BashServerToolEngine as BashServerToolEngine
from pyfect.ai.openrouter.generated._schemas_0 import ContainerFileIds as ContainerFileIds
from pyfect.ai.openrouter.generated._schemas_0 import ContainerNetworkPolicy as ContainerNetworkPolicy
from pyfect.ai.openrouter.generated._schemas_0 import ContainerAutoEnvironment as ContainerAutoEnvironment
from pyfect.ai.openrouter.generated._schemas_0 import ContainerReferenceEnvironment as ContainerReferenceEnvironment
from pyfect.ai.openrouter.generated._schemas_0 import BashServerToolEnvironment as BashServerToolEnvironment
from pyfect.ai.openrouter.generated._schemas_0 import BashServerToolConfig as BashServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import BashServerTool as BashServerTool
from pyfect.ai.openrouter.generated._schemas_0 import DatetimeServerToolConfig as DatetimeServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import DatetimeServerTool as DatetimeServerTool
from pyfect.ai.openrouter.generated._schemas_0 import FilesServerToolConfig as FilesServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import FilesServerTool as FilesServerTool
from pyfect.ai.openrouter.generated._schemas_0 import FusionServerToolConfig as FusionServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import FusionServerTool_OpenRouter as FusionServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationServerToolConfig as ImageGenerationServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationServerTool_OpenRouter as ImageGenerationServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import SearchModelsServerToolConfig as SearchModelsServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ChatSearchModelsServerTool as ChatSearchModelsServerTool
from pyfect.ai.openrouter.generated._schemas_0 import SubagentReasoning as SubagentReasoning
from pyfect.ai.openrouter.generated._schemas_0 import SubagentNestedTool as SubagentNestedTool
from pyfect.ai.openrouter.generated._schemas_0 import SubagentServerToolConfig as SubagentServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import SubagentServerTool_OpenRouter as SubagentServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import WebFetchEngineEnum as WebFetchEngineEnum
from pyfect.ai.openrouter.generated._schemas_0 import WebFetchServerToolConfig as WebFetchServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import WebFetchServerTool as WebFetchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import SearchQualityLevel as SearchQualityLevel
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchUserLocationServerTool as WebSearchUserLocationServerTool
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchConfig as WebSearchConfig
from pyfect.ai.openrouter.generated._schemas_0 import OpenRouterWebSearchServerTool as OpenRouterWebSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ChatWebSearchShorthand as ChatWebSearchShorthand
from pyfect.ai.openrouter.generated._schemas_0 import ChatDynamicServerTool as ChatDynamicServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ChatFunctionTool as ChatFunctionTool
from pyfect.ai.openrouter.generated._schemas_0 import ChatRequest as ChatRequest
from pyfect.ai.openrouter.generated._schemas_0 import ChatFinishReasonEnum as ChatFinishReasonEnum
from pyfect.ai.openrouter.generated._schemas_0 import ChatTokenLogprob as ChatTokenLogprob
from pyfect.ai.openrouter.generated._schemas_0 import ChatTokenLogprobs as ChatTokenLogprobs
from pyfect.ai.openrouter.generated._schemas_0 import ChatChoice as ChatChoice
from pyfect.ai.openrouter.generated._schemas_0 import ChatUsage as ChatUsage
from pyfect.ai.openrouter.generated._schemas_0 import ChatResult as ChatResult
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamReasoningDetails as ChatStreamReasoningDetails
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamToolCall as ChatStreamToolCall
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamDelta as ChatStreamDelta
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamChoice as ChatStreamChoice
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamChunk as ChatStreamChunk
from pyfect.ai.openrouter.generated._schemas_0 import ChatStreamingResponse as ChatStreamingResponse
from pyfect.ai.openrouter.generated._schemas_0 import UnprocessableEntityResponseErrorData as UnprocessableEntityResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import UnprocessableEntityResponse as UnprocessableEntityResponse
from pyfect.ai.openrouter.generated._schemas_0 import TaskClassificationModel as TaskClassificationModel
from pyfect.ai.openrouter.generated._schemas_0 import TaskClassificationItem as TaskClassificationItem
from pyfect.ai.openrouter.generated._schemas_0 import TaskClassificationMacroCategory as TaskClassificationMacroCategory
from pyfect.ai.openrouter.generated._schemas_0 import TaskClassificationResponse as TaskClassificationResponse
from pyfect.ai.openrouter.generated._schemas_0 import ContainerFile as ContainerFile
from pyfect.ai.openrouter.generated._schemas_0 import ContainerFileListResponse as ContainerFileListResponse
from pyfect.ai.openrouter.generated._schemas_0 import OpenRouterFile as OpenRouterFile
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIFile as OpenAIFile
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicFile as AnthropicFile
from pyfect.ai.openrouter.generated._schemas_0 import FileResponse as FileResponse
from pyfect.ai.openrouter.generated._schemas_0 import ClientClosedRequestResponseErrorData as ClientClosedRequestResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import ClientClosedRequestResponse as ClientClosedRequestResponse
from pyfect.ai.openrouter.generated._schemas_0 import GoneResponseErrorData as GoneResponseErrorData
from pyfect.ai.openrouter.generated._schemas_0 import GoneResponse as GoneResponse
from pyfect.ai.openrouter.generated._schemas_0 import CreateCreditPurchaseRequest as CreateCreditPurchaseRequest
from pyfect.ai.openrouter.generated._schemas_0 import CreditPurchase as CreditPurchase
from pyfect.ai.openrouter.generated._schemas_0 import CreditPurchaseResponse as CreditPurchaseResponse
from pyfect.ai.openrouter.generated._schemas_0 import AppRankingsItem as AppRankingsItem
from pyfect.ai.openrouter.generated._schemas_0 import RankingsDailyMeta as RankingsDailyMeta
from pyfect.ai.openrouter.generated._schemas_0 import AppRankingsResponse as AppRankingsResponse
from pyfect.ai.openrouter.generated._schemas_0 import RankingsDailyItem as RankingsDailyItem
from pyfect.ai.openrouter.generated._schemas_0 import RankingsDailyResponse as RankingsDailyResponse
from pyfect.ai.openrouter.generated._schemas_0 import SessionCostItem as SessionCostItem
from pyfect.ai.openrouter.generated._schemas_0 import SessionCostMeta as SessionCostMeta
from pyfect.ai.openrouter.generated._schemas_0 import SessionCostResponse as SessionCostResponse
from pyfect.ai.openrouter.generated._schemas_0 import MultimodalMedia as MultimodalMedia
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartInputAudio as ContentPartInputAudio
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartInputVideo as ContentPartInputVideo
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartInputFile as ContentPartInputFile
from pyfect.ai.openrouter.generated._schemas_0 import ModelAliasTarget as ModelAliasTarget
from pyfect.ai.openrouter.generated._schemas_0 import InputModality as InputModality
from pyfect.ai.openrouter.generated._schemas_0 import InstructType as InstructType
from pyfect.ai.openrouter.generated._schemas_0 import OutputModality as OutputModality
from pyfect.ai.openrouter.generated._schemas_0 import ModelGroup as ModelGroup
from pyfect.ai.openrouter.generated._schemas_0 import ModelArchitecture as ModelArchitecture
from pyfect.ai.openrouter.generated._schemas_0 import AABenchmarkEntry as AABenchmarkEntry
from pyfect.ai.openrouter.generated._schemas_0 import DABenchmarkEntry as DABenchmarkEntry
from pyfect.ai.openrouter.generated._schemas_0 import ModelBenchmarks as ModelBenchmarks
from pyfect.ai.openrouter.generated._schemas_0 import DefaultParameters as DefaultParameters
from pyfect.ai.openrouter.generated._schemas_0 import ModelLinks as ModelLinks
from pyfect.ai.openrouter.generated._schemas_0 import PerRequestLimits as PerRequestLimits
from pyfect.ai.openrouter.generated._schemas_0 import PricingOverride as PricingOverride
from pyfect.ai.openrouter.generated._schemas_0 import PublicPricing as PublicPricing
from pyfect.ai.openrouter.generated._schemas_0 import ModelReasoning as ModelReasoning
from pyfect.ai.openrouter.generated._schemas_0 import Parameter as Parameter
from pyfect.ai.openrouter.generated._schemas_0 import TopProviderInfo as TopProviderInfo
from pyfect.ai.openrouter.generated._schemas_0 import Model as Model
from pyfect.ai.openrouter.generated._schemas_0 import ModelsListResponseData as ModelsListResponseData
from pyfect.ai.openrouter.generated._schemas_0 import ModelsListResponse as ModelsListResponse
from pyfect.ai.openrouter.generated._schemas_0 import PercentileStats as PercentileStats
from pyfect.ai.openrouter.generated._schemas_0 import NativeTools as NativeTools
from pyfect.ai.openrouter.generated._schemas_0 import Decisions as Decisions
from pyfect.ai.openrouter.generated._schemas_0 import Embeddings as Embeddings
from pyfect.ai.openrouter.generated._schemas_0 import Extractions as Extractions
from pyfect.ai.openrouter.generated._schemas_0 import ImageGeneration as ImageGeneration
from pyfect.ai.openrouter.generated._schemas_0 import Rerank as Rerank
from pyfect.ai.openrouter.generated._schemas_0 import STT as STT
from pyfect.ai.openrouter.generated._schemas_0 import TextGeneration as TextGeneration
from pyfect.ai.openrouter.generated._schemas_0 import TTS as TTS
from pyfect.ai.openrouter.generated._schemas_0 import Unknown as Unknown
from pyfect.ai.openrouter.generated._schemas_0 import VideoGeneration as VideoGeneration
from pyfect.ai.openrouter.generated._schemas_0 import PerfLast30mByWorkload as PerfLast30mByWorkload
from pyfect.ai.openrouter.generated._schemas_0 import Pricing as Pricing
from pyfect.ai.openrouter.generated._schemas_0 import PublicServiceTier as PublicServiceTier
from pyfect.ai.openrouter.generated._schemas_0 import EndpointStatus as EndpointStatus
from pyfect.ai.openrouter.generated._schemas_0 import ToolChoiceSupport as ToolChoiceSupport
from pyfect.ai.openrouter.generated._schemas_0 import PublicZdrEndpoint as PublicZdrEndpoint
from pyfect.ai.openrouter.generated._schemas_0 import ExternalUser as ExternalUser
from pyfect.ai.openrouter.generated._schemas_0 import ListExternalUsersResponse as ListExternalUsersResponse
from pyfect.ai.openrouter.generated._schemas_0 import CreateExternalUserRequest as CreateExternalUserRequest
from pyfect.ai.openrouter.generated._schemas_0 import ExternalUserResponse as ExternalUserResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateExternalUserRequest as UpdateExternalUserRequest
from pyfect.ai.openrouter.generated._schemas_0 import FileProvider as FileProvider
from pyfect.ai.openrouter.generated._schemas_0 import OpenRouterFileList as OpenRouterFileList
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIFileList as OpenAIFileList
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicFileList as AnthropicFileList
from pyfect.ai.openrouter.generated._schemas_0 import FileListResponse as FileListResponse
from pyfect.ai.openrouter.generated._schemas_0 import __ClientMultipartFile as __ClientMultipartFile
from pyfect.ai.openrouter.generated._schemas_0 import OpenRouterFileDeleted as OpenRouterFileDeleted
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIFileDeleted as OpenAIFileDeleted
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicFileDeleted as AnthropicFileDeleted
from pyfect.ai.openrouter.generated._schemas_0 import FileDeleteResponse as FileDeleteResponse
from pyfect.ai.openrouter.generated._schemas_0 import ProviderResponse as ProviderResponse
from pyfect.ai.openrouter.generated._schemas_0 import GenerationResponse as GenerationResponse
from pyfect.ai.openrouter.generated._schemas_0 import GenerationContentErrorAttempt as GenerationContentErrorAttempt
from pyfect.ai.openrouter.generated._schemas_0 import GenerationContentError as GenerationContentError
from pyfect.ai.openrouter.generated._schemas_0 import GenerationContentData as GenerationContentData
from pyfect.ai.openrouter.generated._schemas_0 import GenerationContentResponse as GenerationContentResponse
from pyfect.ai.openrouter.generated._schemas_0 import SubmitGenerationFeedbackRequest as SubmitGenerationFeedbackRequest
from pyfect.ai.openrouter.generated._schemas_0 import SubmitGenerationFeedbackResponse as SubmitGenerationFeedbackResponse
from pyfect.ai.openrouter.generated._schemas_0 import GuardrailDataRegion as GuardrailDataRegion
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterBuiltinAction as ContentFilterBuiltinAction
from pyfect.ai.openrouter.generated._schemas_0 import PromptInjectionScanScope as PromptInjectionScanScope
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterBuiltinSlug as ContentFilterBuiltinSlug
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterBuiltinEntry as ContentFilterBuiltinEntry
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterAction as ContentFilterAction
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterEntry as ContentFilterEntry
from pyfect.ai.openrouter.generated._schemas_0 import GuardrailInterval as GuardrailInterval
from pyfect.ai.openrouter.generated._schemas_0 import Guardrail as Guardrail
from pyfect.ai.openrouter.generated._schemas_0 import ListGuardrailsResponse as ListGuardrailsResponse
from pyfect.ai.openrouter.generated._schemas_0 import ContentFilterBuiltinEntryInput as ContentFilterBuiltinEntryInput
from pyfect.ai.openrouter.generated._schemas_0 import CreateGuardrailRequest as CreateGuardrailRequest
from pyfect.ai.openrouter.generated._schemas_0 import CreateGuardrailResponse as CreateGuardrailResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetGuardrailResponse as GetGuardrailResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteGuardrailResponse as DeleteGuardrailResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateGuardrailRequest as UpdateGuardrailRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpdateGuardrailResponse as UpdateGuardrailResponse
from pyfect.ai.openrouter.generated._schemas_0 import KeyAssignment as KeyAssignment
from pyfect.ai.openrouter.generated._schemas_0 import ListKeyAssignmentsResponse as ListKeyAssignmentsResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkAssignKeysRequest as BulkAssignKeysRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkAssignKeysResponse as BulkAssignKeysResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkUnassignKeysRequest as BulkUnassignKeysRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkUnassignKeysResponse as BulkUnassignKeysResponse
from pyfect.ai.openrouter.generated._schemas_0 import MemberAssignment as MemberAssignment
from pyfect.ai.openrouter.generated._schemas_0 import ListMemberAssignmentsResponse as ListMemberAssignmentsResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkAssignMembersRequest as BulkAssignMembersRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkAssignMembersResponse as BulkAssignMembersResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkUnassignMembersRequest as BulkUnassignMembersRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkUnassignMembersResponse as BulkUnassignMembersResponse
from pyfect.ai.openrouter.generated._schemas_0 import GuardrailBudgetPolicyConfig as GuardrailBudgetPolicyConfig
from pyfect.ai.openrouter.generated._schemas_0 import BudgetAccountGuardrailPolicy as BudgetAccountGuardrailPolicy
from pyfect.ai.openrouter.generated._schemas_0 import GuardrailModerationPolicyConfig as GuardrailModerationPolicyConfig
from pyfect.ai.openrouter.generated._schemas_0 import ModerationAccountGuardrailPolicy as ModerationAccountGuardrailPolicy
from pyfect.ai.openrouter.generated._schemas_0 import GuardrailModelAvailabilityPolicyConfig as GuardrailModelAvailabilityPolicyConfig
from pyfect.ai.openrouter.generated._schemas_0 import ModelAvailabilityAccountGuardrailPolicy as ModelAvailabilityAccountGuardrailPolicy
from pyfect.ai.openrouter.generated._schemas_0 import AccountGuardrailPolicy as AccountGuardrailPolicy
from pyfect.ai.openrouter.generated._schemas_0 import ListAccountGuardrailPoliciesResponse as ListAccountGuardrailPoliciesResponse
from pyfect.ai.openrouter.generated._schemas_0 import GuardrailBudgetPolicyAuthoringConfig as GuardrailBudgetPolicyAuthoringConfig
from pyfect.ai.openrouter.generated._schemas_0 import BudgetAccountGuardrailPolicyRequest as BudgetAccountGuardrailPolicyRequest
from pyfect.ai.openrouter.generated._schemas_0 import ModerationAccountGuardrailPolicyRequest as ModerationAccountGuardrailPolicyRequest
from pyfect.ai.openrouter.generated._schemas_0 import GuardrailModelAvailabilityPolicyAuthoringConfig as GuardrailModelAvailabilityPolicyAuthoringConfig
from pyfect.ai.openrouter.generated._schemas_0 import ModelAvailabilityAccountGuardrailPolicyRequest as ModelAvailabilityAccountGuardrailPolicyRequest
from pyfect.ai.openrouter.generated._schemas_0 import AccountGuardrailPolicyRequest as AccountGuardrailPolicyRequest
from pyfect.ai.openrouter.generated._schemas_0 import AccountGuardrailPolicyResponse as AccountGuardrailPolicyResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteGuardrailPolicyResponse as DeleteGuardrailPolicyResponse
from pyfect.ai.openrouter.generated._schemas_0 import GuardrailPolicyAssignmentState as GuardrailPolicyAssignmentState
from pyfect.ai.openrouter.generated._schemas_0 import GuardrailPolicyAssignmentResponse as GuardrailPolicyAssignmentResponse
from pyfect.ai.openrouter.generated._schemas_0 import ChangeGuardrailPolicyAssignmentRequest as ChangeGuardrailPolicyAssignmentRequest
from pyfect.ai.openrouter.generated._schemas_0 import ChangeGuardrailPolicyAssignmentResponse as ChangeGuardrailPolicyAssignmentResponse
from pyfect.ai.openrouter.generated._schemas_0 import BudgetGuardrailPolicySummary as BudgetGuardrailPolicySummary
from pyfect.ai.openrouter.generated._schemas_0 import ListBudgetGuardrailPoliciesResponse as ListBudgetGuardrailPoliciesResponse
from pyfect.ai.openrouter.generated._schemas_0 import CreateBudgetGuardrailPolicyRequest as CreateBudgetGuardrailPolicyRequest
from pyfect.ai.openrouter.generated._schemas_0 import BudgetGuardrailPolicy as BudgetGuardrailPolicy
from pyfect.ai.openrouter.generated._schemas_0 import BudgetGuardrailPolicyResponse as BudgetGuardrailPolicyResponse
from pyfect.ai.openrouter.generated._schemas_0 import BudgetGuardrailPolicyDetail as BudgetGuardrailPolicyDetail
from pyfect.ai.openrouter.generated._schemas_0 import BudgetGuardrailPolicyDetailResponse as BudgetGuardrailPolicyDetailResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateBudgetGuardrailPolicyRequest as UpdateBudgetGuardrailPolicyRequest
from pyfect.ai.openrouter.generated._schemas_0 import ModelAvailabilityGuardrailPolicySummary as ModelAvailabilityGuardrailPolicySummary
from pyfect.ai.openrouter.generated._schemas_0 import ListModelAvailabilityGuardrailPoliciesResponse as ListModelAvailabilityGuardrailPoliciesResponse
from pyfect.ai.openrouter.generated._schemas_0 import CreateModelAvailabilityGuardrailPolicyRequest as CreateModelAvailabilityGuardrailPolicyRequest
from pyfect.ai.openrouter.generated._schemas_0 import ModelAvailabilityGuardrailPolicy as ModelAvailabilityGuardrailPolicy
from pyfect.ai.openrouter.generated._schemas_0 import ModelAvailabilityGuardrailPolicyResponse as ModelAvailabilityGuardrailPolicyResponse
from pyfect.ai.openrouter.generated._schemas_0 import ModelAvailabilityGuardrailPolicyDetail as ModelAvailabilityGuardrailPolicyDetail
from pyfect.ai.openrouter.generated._schemas_0 import ModelAvailabilityGuardrailPolicyDetailResponse as ModelAvailabilityGuardrailPolicyDetailResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateModelAvailabilityGuardrailPolicyRequest as UpdateModelAvailabilityGuardrailPolicyRequest
from pyfect.ai.openrouter.generated._schemas_0 import ModerationGuardrailPolicySummary as ModerationGuardrailPolicySummary
from pyfect.ai.openrouter.generated._schemas_0 import ListModerationGuardrailPoliciesResponse as ListModerationGuardrailPoliciesResponse
from pyfect.ai.openrouter.generated._schemas_0 import CreateModerationGuardrailPolicyRequest as CreateModerationGuardrailPolicyRequest
from pyfect.ai.openrouter.generated._schemas_0 import ModerationGuardrailPolicy as ModerationGuardrailPolicy
from pyfect.ai.openrouter.generated._schemas_0 import ModerationGuardrailPolicyResponse as ModerationGuardrailPolicyResponse
from pyfect.ai.openrouter.generated._schemas_0 import ModerationGuardrailPolicyDetail as ModerationGuardrailPolicyDetail
from pyfect.ai.openrouter.generated._schemas_0 import ModerationGuardrailPolicyDetailResponse as ModerationGuardrailPolicyDetailResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateModerationGuardrailPolicyRequest as UpdateModerationGuardrailPolicyRequest
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartImage as ContentPartImage
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationProviderPreferences as ImageGenerationProviderPreferences
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationRequest as ImageGenerationRequest
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationUsage as ImageGenerationUsage
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenerationResponse as ImageGenerationResponse
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenPartialImageEvent as ImageGenPartialImageEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenTextChunkEvent as ImageGenTextChunkEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenCompletedEvent as ImageGenCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenStreamErrorEvent as ImageGenStreamErrorEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageStreamingResponse as ImageStreamingResponse
from pyfect.ai.openrouter.generated._schemas_0 import ImageInputModality as ImageInputModality
from pyfect.ai.openrouter.generated._schemas_0 import ImageOutputModality as ImageOutputModality
from pyfect.ai.openrouter.generated._schemas_0 import ImageModelArchitecture as ImageModelArchitecture
from pyfect.ai.openrouter.generated._schemas_0 import EnumCapability as EnumCapability
from pyfect.ai.openrouter.generated._schemas_0 import RangeCapability as RangeCapability
from pyfect.ai.openrouter.generated._schemas_0 import BooleanCapability as BooleanCapability
from pyfect.ai.openrouter.generated._schemas_0 import CapabilityDescriptor as CapabilityDescriptor
from pyfect.ai.openrouter.generated._schemas_0 import SupportedParameters as SupportedParameters
from pyfect.ai.openrouter.generated._schemas_0 import ImageModelListItem as ImageModelListItem
from pyfect.ai.openrouter.generated._schemas_0 import ImageModelsListResponse as ImageModelsListResponse
from pyfect.ai.openrouter.generated._schemas_0 import ImagePricingEntry as ImagePricingEntry
from pyfect.ai.openrouter.generated._schemas_0 import ImageEndpoint as ImageEndpoint
from pyfect.ai.openrouter.generated._schemas_0 import ImageModelEndpointsResponse as ImageModelEndpointsResponse
from pyfect.ai.openrouter.generated._schemas_0 import KeyBudget as KeyBudget
from pyfect.ai.openrouter.generated._schemas_0 import FreeModelDailyRequests as FreeModelDailyRequests
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicInputTokensClearAtLeast as AnthropicInputTokensClearAtLeast
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolUsesKeep as AnthropicToolUsesKeep
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicInputTokensTrigger as AnthropicInputTokensTrigger
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolUsesTrigger as AnthropicToolUsesTrigger
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicThinkingTurns as AnthropicThinkingTurns
from pyfect.ai.openrouter.generated._schemas_0 import MessagesFallbackParam as MessagesFallbackParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicSystemClearAt as AnthropicSystemClearAt
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationCharLocationParam as AnthropicCitationCharLocationParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationPageLocationParam as AnthropicCitationPageLocationParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationContentBlockLocationParam as AnthropicCitationContentBlockLocationParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationWebSearchResultLocationParam as AnthropicCitationWebSearchResultLocationParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicCitationSearchResultLocationParam as AnthropicCitationSearchResultLocationParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicTextBlockParam as AnthropicTextBlockParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicImageMimeType as AnthropicImageMimeType
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicBase64ImageSource as AnthropicBase64ImageSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicUrlImageSource as AnthropicUrlImageSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicFileDocumentSource as AnthropicFileDocumentSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicImageBlockParam as AnthropicImageBlockParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicUrlPdfSource as AnthropicUrlPdfSource
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicDocumentBlockParam as AnthropicDocumentBlockParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicSearchResultBlockParam as AnthropicSearchResultBlockParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebSearchResultBlockParam as AnthropicWebSearchResultBlockParam
from pyfect.ai.openrouter.generated._schemas_0 import MessagesAdvisorToolResultBlock as MessagesAdvisorToolResultBlock
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicWebSearchToolUserLocation as AnthropicWebSearchToolUserLocation
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicAllowedCallers as AnthropicAllowedCallers
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolUnion as AnthropicToolUnion
from pyfect.ai.openrouter.generated._schemas_0 import MessagesToolAdditionBlock as MessagesToolAdditionBlock
from pyfect.ai.openrouter.generated._schemas_0 import MessagesToolRemovalBlock as MessagesToolRemovalBlock
from pyfect.ai.openrouter.generated._schemas_0 import MessagesShellToolResultBlock as MessagesShellToolResultBlock
from pyfect.ai.openrouter.generated._schemas_0 import MessagesBashToolResultBlock as MessagesBashToolResultBlock
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicToolSearchResultParam as ORAnthropicToolSearchResultParam
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicOutputEffort as AnthropicOutputEffort
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicMessageOutputConfig as AnthropicMessageOutputConfig
from pyfect.ai.openrouter.generated._schemas_0 import MessagesMessageParam as MessagesMessageParam
from pyfect.ai.openrouter.generated._schemas_0 import MessagesOutputConfig as MessagesOutputConfig
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicSafeguard as AnthropicSafeguard
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicThinkingBlockBinding as AnthropicThinkingBlockBinding
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicThinkingDisplay as AnthropicThinkingDisplay
from pyfect.ai.openrouter.generated._schemas_0 import MessagesSearchModelsServerTool as MessagesSearchModelsServerTool
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchToolBm25 as AnthropicToolSearchToolBm25
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicToolSearchToolRegex as AnthropicToolSearchToolRegex
from pyfect.ai.openrouter.generated._schemas_0 import ShellServerToolEngine as ShellServerToolEngine
from pyfect.ai.openrouter.generated._schemas_0 import ShellServerToolEnvironment as ShellServerToolEnvironment
from pyfect.ai.openrouter.generated._schemas_0 import ShellServerToolConfig as ShellServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ShellServerTool_OpenRouter as ShellServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import ToolSearchServerToolConfig as ToolSearchServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ToolSearchServerTool as ToolSearchServerTool
from pyfect.ai.openrouter.generated._schemas_0 import MessagesRequest as MessagesRequest
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicSafeguardResult as AnthropicSafeguardResult
from pyfect.ai.openrouter.generated._schemas_0 import MessagesResult as MessagesResult
from pyfect.ai.openrouter.generated._schemas_0 import MessagesStartEvent as MessagesStartEvent
from pyfect.ai.openrouter.generated._schemas_0 import ORAnthropicServerToolUsage as ORAnthropicServerToolUsage
from pyfect.ai.openrouter.generated._schemas_0 import MessagesDeltaEvent as MessagesDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesStopEvent as MessagesStopEvent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesContentBlockStartEvent as MessagesContentBlockStartEvent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesContentBlockDeltaEvent as MessagesContentBlockDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesContentBlockStopEvent as MessagesContentBlockStopEvent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesPingEvent as MessagesPingEvent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesErrorEvent as MessagesErrorEvent
from pyfect.ai.openrouter.generated._schemas_0 import MessagesStreamEvents as MessagesStreamEvents
from pyfect.ai.openrouter.generated._schemas_0 import MessagesStreamingResponse as MessagesStreamingResponse
from pyfect.ai.openrouter.generated._schemas_0 import AnthropicMessagesErrorResponse as AnthropicMessagesErrorResponse
from pyfect.ai.openrouter.generated._schemas_0 import ModelResponse as ModelResponse
from pyfect.ai.openrouter.generated._schemas_0 import PublicEndpoint as PublicEndpoint
from pyfect.ai.openrouter.generated._schemas_0 import ListEndpointsResponse as ListEndpointsResponse
from pyfect.ai.openrouter.generated._schemas_0 import ModelsCountResponse as ModelsCountResponse
from pyfect.ai.openrouter.generated._schemas_0 import OAuthJwks as OAuthJwks
from pyfect.ai.openrouter.generated._schemas_0 import TokenExchangeRequest as TokenExchangeRequest
from pyfect.ai.openrouter.generated._schemas_0 import TokenExchangeResponse as TokenExchangeResponse
from pyfect.ai.openrouter.generated._schemas_0 import OAuthErrorResponse as OAuthErrorResponse
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityFilterRuleGroup as ObservabilityFilterRuleGroup
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityFilterRulesConfig as ObservabilityFilterRulesConfig
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityDataRegion as ObservabilityDataRegion
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
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityDestination as ObservabilityDestination
from pyfect.ai.openrouter.generated._schemas_0 import ListObservabilityDestinationsResponse as ListObservabilityDestinationsResponse
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityFilterRulesConfigNullable as ObservabilityFilterRulesConfigNullable
from pyfect.ai.openrouter.generated._schemas_0 import ObservabilityDataRegionInput as ObservabilityDataRegionInput
from pyfect.ai.openrouter.generated._schemas_0 import CreateObservabilityDestinationRequest as CreateObservabilityDestinationRequest
from pyfect.ai.openrouter.generated._schemas_0 import CreateObservabilityDestinationResponse as CreateObservabilityDestinationResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetObservabilityDestinationResponse as GetObservabilityDestinationResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteObservabilityDestinationResponse as DeleteObservabilityDestinationResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateObservabilityDestinationRequest as UpdateObservabilityDestinationRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpdateObservabilityDestinationResponse as UpdateObservabilityDestinationResponse
from pyfect.ai.openrouter.generated._schemas_0 import OrganizationSettings as OrganizationSettings
from pyfect.ai.openrouter.generated._schemas_0 import UpdateOrganizationSettingsRequest as UpdateOrganizationSettingsRequest
from pyfect.ai.openrouter.generated._schemas_0 import PresetStatus as PresetStatus
from pyfect.ai.openrouter.generated._schemas_0 import Preset as Preset
from pyfect.ai.openrouter.generated._schemas_0 import ListPresetsResponse as ListPresetsResponse
from pyfect.ai.openrouter.generated._schemas_0 import PresetDesignatedVersion as PresetDesignatedVersion
from pyfect.ai.openrouter.generated._schemas_0 import PresetWithDesignatedVersion as PresetWithDesignatedVersion
from pyfect.ai.openrouter.generated._schemas_0 import GetPresetResponse as GetPresetResponse
from pyfect.ai.openrouter.generated._schemas_0 import CreatePresetFromInferenceResponse as CreatePresetFromInferenceResponse
from pyfect.ai.openrouter.generated._schemas_0 import ResponseIncludesEnum as ResponseIncludesEnum
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningItem as ReasoningItem
from pyfect.ai.openrouter.generated._schemas_0 import InputVideo as InputVideo
from pyfect.ai.openrouter.generated._schemas_0 import EasyInputMessage as EasyInputMessage
from pyfect.ai.openrouter.generated._schemas_0 import InputMessageItem as InputMessageItem
from pyfect.ai.openrouter.generated._schemas_0 import FunctionCallItem as FunctionCallItem
from pyfect.ai.openrouter.generated._schemas_0 import FunctionCallOutputItem as FunctionCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputWebSearchCallItem as OutputWebSearchCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputFileSearchCallItem as OutputFileSearchCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputImageGenerationCallItem as OutputImageGenerationCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputCodeInterpreterCallItem as OutputCodeInterpreterCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputComputerCallItem as OutputComputerCallItem
from pyfect.ai.openrouter.generated._schemas_0 import FailableToolCallStatus as FailableToolCallStatus
from pyfect.ai.openrouter.generated._schemas_0 import OutputDatetimeItem as OutputDatetimeItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputWebSearchServerToolItem as OutputWebSearchServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputCodeInterpreterServerToolItem as OutputCodeInterpreterServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputFileSearchServerToolItem as OutputFileSearchServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputImageGenerationServerToolItem as OutputImageGenerationServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputBrowserUseServerToolItem as OutputBrowserUseServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputBashServerToolItem as OutputBashServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputTextEditorServerToolItem as OutputTextEditorServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputApplyPatchServerToolItem as OutputApplyPatchServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputWebFetchServerToolItem as OutputWebFetchServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputToolSearchServerToolItem as OutputToolSearchServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputMemoryServerToolItem as OutputMemoryServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputArmorBlockedItem as OutputArmorBlockedItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputSearchModelsServerToolItem as OutputSearchModelsServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import FusionAnalysisResult as FusionAnalysisResult
from pyfect.ai.openrouter.generated._schemas_0 import FusionSource as FusionSource
from pyfect.ai.openrouter.generated._schemas_0 import OutputFusionServerToolItem as OutputFusionServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputAdvisorServerToolItem as OutputAdvisorServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputSubagentServerToolItem as OutputSubagentServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputFilesServerToolItem as OutputFilesServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import ShellCallOutputContent as ShellCallOutputContent
from pyfect.ai.openrouter.generated._schemas_0 import OutputShellServerToolItem as OutputShellServerToolItem
from pyfect.ai.openrouter.generated._schemas_0 import LocalShellCallItem as LocalShellCallItem
from pyfect.ai.openrouter.generated._schemas_0 import LocalShellCallOutputItem as LocalShellCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import ShellCallItem as ShellCallItem
from pyfect.ai.openrouter.generated._schemas_0 import ShellCallOutputItem as ShellCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import McpListToolsItem as McpListToolsItem
from pyfect.ai.openrouter.generated._schemas_0 import McpApprovalRequestItem as McpApprovalRequestItem
from pyfect.ai.openrouter.generated._schemas_0 import McpApprovalResponseItem as McpApprovalResponseItem
from pyfect.ai.openrouter.generated._schemas_0 import McpProtocolError as McpProtocolError
from pyfect.ai.openrouter.generated._schemas_0 import McpToolExecutionError as McpToolExecutionError
from pyfect.ai.openrouter.generated._schemas_0 import McpHttpError as McpHttpError
from pyfect.ai.openrouter.generated._schemas_0 import McpToolCallError as McpToolCallError
from pyfect.ai.openrouter.generated._schemas_0 import McpCallItem as McpCallItem
from pyfect.ai.openrouter.generated._schemas_0 import CustomToolCallItem as CustomToolCallItem
from pyfect.ai.openrouter.generated._schemas_0 import CustomToolCallOutputItem as CustomToolCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import CompactionTriggerItem as CompactionTriggerItem
from pyfect.ai.openrouter.generated._schemas_0 import CompactionItem as CompactionItem
from pyfect.ai.openrouter.generated._schemas_0 import ContextCompactionItem as ContextCompactionItem
from pyfect.ai.openrouter.generated._schemas_0 import ItemReferenceItem as ItemReferenceItem
from pyfect.ai.openrouter.generated._schemas_0 import SearchModelsServerTool_OpenRouter as SearchModelsServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchServerToolConfig as WebSearchServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchServerTool_OpenRouter as WebSearchServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchEngineEnum as ApplyPatchEngineEnum
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchServerToolConfig as ApplyPatchServerToolConfig
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchServerTool_OpenRouter as ApplyPatchServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import McpServerToolParameters as McpServerToolParameters
from pyfect.ai.openrouter.generated._schemas_0 import McpServerTool_OpenRouter as McpServerTool_OpenRouter
from pyfect.ai.openrouter.generated._schemas_0 import AdditionalToolsItem as AdditionalToolsItem
from pyfect.ai.openrouter.generated._schemas_0 import AgentMessageItem as AgentMessageItem
from pyfect.ai.openrouter.generated._schemas_0 import ToolSearchCallItem as ToolSearchCallItem
from pyfect.ai.openrouter.generated._schemas_0 import ToolSearchOutputItem as ToolSearchOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import Inputs as Inputs
from pyfect.ai.openrouter.generated._schemas_0 import OutputModalityEnum as OutputModalityEnum
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningConfig as ReasoningConfig
from pyfect.ai.openrouter.generated._schemas_0 import TextExtendedConfig as TextExtendedConfig
from pyfect.ai.openrouter.generated._schemas_0 import OpenAIResponsesTruncation as OpenAIResponsesTruncation
from pyfect.ai.openrouter.generated._schemas_0 import ResponsesRequest as ResponsesRequest
from pyfect.ai.openrouter.generated._schemas_0 import ListPresetVersionsResponse as ListPresetVersionsResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetPresetVersionResponse as GetPresetVersionResponse
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointStatus as PrivateEndpointStatus
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointSummary as PrivateEndpointSummary
from pyfect.ai.openrouter.generated._schemas_0 import ListPrivateEndpointsResponse as ListPrivateEndpointsResponse
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointActivation as PrivateEndpointActivation
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointDeclaredParameter as PrivateEndpointDeclaredParameter
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointPricing as PrivateEndpointPricing
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointQuantization as PrivateEndpointQuantization
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointReasoningReturnMechanism as PrivateEndpointReasoningReturnMechanism
from pyfect.ai.openrouter.generated._schemas_0 import UpdatePrivateEndpointSettingsRequest as UpdatePrivateEndpointSettingsRequest
from pyfect.ai.openrouter.generated._schemas_0 import CreatePrivateEndpointRequest as CreatePrivateEndpointRequest
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointDeclaredRegion as PrivateEndpointDeclaredRegion
from pyfect.ai.openrouter.generated._schemas_0 import ManagedPrivateEndpoint as ManagedPrivateEndpoint
from pyfect.ai.openrouter.generated._schemas_0 import ManagedPrivateEndpointResponse as ManagedPrivateEndpointResponse
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointCheckReason as PrivateEndpointCheckReason
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointCheck as PrivateEndpointCheck
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointParameterCheck as PrivateEndpointParameterCheck
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointValidationNullable as PrivateEndpointValidationNullable
from pyfect.ai.openrouter.generated._schemas_0 import CreatePrivateEndpointValidationFailedResponse as CreatePrivateEndpointValidationFailedResponse
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointSettings as PrivateEndpointSettings
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpoint as PrivateEndpoint
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointResponse as PrivateEndpointResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeletePrivateEndpointResponse as DeletePrivateEndpointResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdatePrivateEndpointRequest as UpdatePrivateEndpointRequest
from pyfect.ai.openrouter.generated._schemas_0 import ValidatePrivateEndpointRequest as ValidatePrivateEndpointRequest
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointValidation as PrivateEndpointValidation
from pyfect.ai.openrouter.generated._schemas_0 import PrivateEndpointValidationResponse as PrivateEndpointValidationResponse
from pyfect.ai.openrouter.generated._schemas_0 import PrivateProvider as PrivateProvider
from pyfect.ai.openrouter.generated._schemas_0 import CreatePrivateProviderRequest as CreatePrivateProviderRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpdatePrivateProviderRequest as UpdatePrivateProviderRequest
from pyfect.ai.openrouter.generated._schemas_0 import OpenResponsesCreatedEvent as OpenResponsesCreatedEvent
from pyfect.ai.openrouter.generated._schemas_0 import OpenResponsesInProgressEvent as OpenResponsesInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import StreamEventsResponseCompleted as StreamEventsResponseCompleted
from pyfect.ai.openrouter.generated._schemas_0 import StreamEventsResponseIncomplete as StreamEventsResponseIncomplete
from pyfect.ai.openrouter.generated._schemas_0 import StreamEventsResponseFailed as StreamEventsResponseFailed
from pyfect.ai.openrouter.generated._schemas_0 import ErrorEvent as ErrorEvent
from pyfect.ai.openrouter.generated._schemas_0 import OutputMessageItem as OutputMessageItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputReasoningItem as OutputReasoningItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputFunctionCallItem as OutputFunctionCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputApplyPatchCallItem as OutputApplyPatchCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputCompactionItem as OutputCompactionItem
from pyfect.ai.openrouter.generated._schemas_0 import ShellCallStatus as ShellCallStatus
from pyfect.ai.openrouter.generated._schemas_0 import OutputShellCallItem as OutputShellCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputShellCallOutputItem as OutputShellCallOutputItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputCustomToolCallItem as OutputCustomToolCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputToolSearchCallItem as OutputToolSearchCallItem
from pyfect.ai.openrouter.generated._schemas_0 import OutputItems as OutputItems
from pyfect.ai.openrouter.generated._schemas_0 import StreamEventsResponseOutputItemAdded as StreamEventsResponseOutputItemAdded
from pyfect.ai.openrouter.generated._schemas_0 import StreamEventsResponseOutputItemDone as StreamEventsResponseOutputItemDone
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartAddedEvent as ContentPartAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartDoneEvent as ContentPartDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import TextDeltaEvent as TextDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import TextDoneEvent as TextDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import RefusalDeltaEvent as RefusalDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import RefusalDoneEvent as RefusalDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import AnnotationAddedEvent as AnnotationAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import FunctionCallArgsDeltaEvent as FunctionCallArgsDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import FunctionCallArgsDoneEvent as FunctionCallArgsDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDeltaEvent as ReasoningDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningDoneEvent as ReasoningDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryPartAddedEvent as ReasoningSummaryPartAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryPartDoneEvent as ReasoningSummaryPartDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryTextDeltaEvent as ReasoningSummaryTextDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import ReasoningSummaryTextDoneEvent as ReasoningSummaryTextDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenCallInProgressEvent as ImageGenCallInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenCallGeneratingEvent as ImageGenCallGeneratingEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenCallPartialImageEvent as ImageGenCallPartialImageEvent
from pyfect.ai.openrouter.generated._schemas_0 import ImageGenCallCompletedEvent as ImageGenCallCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterCallInProgressEvent as CodeInterpreterCallInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterCallInterpretingEvent as CodeInterpreterCallInterpretingEvent
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterCallCompletedEvent as CodeInterpreterCallCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterCallCodeDeltaEvent as CodeInterpreterCallCodeDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import CodeInterpreterCallCodeDoneEvent as CodeInterpreterCallCodeDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchCallInProgressEvent as WebSearchCallInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchCallSearchingEvent as WebSearchCallSearchingEvent
from pyfect.ai.openrouter.generated._schemas_0 import WebSearchCallCompletedEvent as WebSearchCallCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import CustomToolCallInputDeltaEvent as CustomToolCallInputDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import CustomToolCallInputDoneEvent as CustomToolCallInputDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallOperationDiffDeltaEvent as ApplyPatchCallOperationDiffDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import ApplyPatchCallOperationDiffDoneEvent as ApplyPatchCallOperationDiffDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallInProgressEvent as FusionCallInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallPanelAddedEvent as FusionCallPanelAddedEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallPanelDeltaEvent as FusionCallPanelDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallPanelReasoningDeltaEvent as FusionCallPanelReasoningDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallPanelCompletedEvent as FusionCallPanelCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallPanelFailedEvent as FusionCallPanelFailedEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallAnalysisInProgressEvent as FusionCallAnalysisInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallAnalysisCompletedEvent as FusionCallAnalysisCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import FusionCallCompletedEvent as FusionCallCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import McpListToolsInProgressEvent as McpListToolsInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import McpListToolsCompletedEvent as McpListToolsCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import McpListToolsFailedEvent as McpListToolsFailedEvent
from pyfect.ai.openrouter.generated._schemas_0 import McpCallInProgressEvent as McpCallInProgressEvent
from pyfect.ai.openrouter.generated._schemas_0 import McpCallArgumentsDeltaEvent as McpCallArgumentsDeltaEvent
from pyfect.ai.openrouter.generated._schemas_0 import McpCallArgumentsDoneEvent as McpCallArgumentsDoneEvent
from pyfect.ai.openrouter.generated._schemas_0 import McpCallCompletedEvent as McpCallCompletedEvent
from pyfect.ai.openrouter.generated._schemas_0 import McpCallFailedEvent as McpCallFailedEvent
from pyfect.ai.openrouter.generated._schemas_0 import DebugEvent as DebugEvent
from pyfect.ai.openrouter.generated._schemas_0 import StreamEvents as StreamEvents
from pyfect.ai.openrouter.generated._schemas_0 import ResponsesStreamingResponse as ResponsesStreamingResponse
from pyfect.ai.openrouter.generated._schemas_0 import ScimGroupMapping as ScimGroupMapping
from pyfect.ai.openrouter.generated._schemas_0 import ListScimGroupMappingsResponse as ListScimGroupMappingsResponse
from pyfect.ai.openrouter.generated._schemas_0 import CreateScimGroupMappingRequest as CreateScimGroupMappingRequest
from pyfect.ai.openrouter.generated._schemas_0 import CreateScimGroupMappingResponse as CreateScimGroupMappingResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetScimGroupMappingResponse as GetScimGroupMappingResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteScimGroupMappingResponse as DeleteScimGroupMappingResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateScimGroupMappingRequest as UpdateScimGroupMappingRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpdateScimGroupMappingResponse as UpdateScimGroupMappingResponse
from pyfect.ai.openrouter.generated._schemas_0 import ScimGroup as ScimGroup
from pyfect.ai.openrouter.generated._schemas_0 import ListScimGroupsResponse as ListScimGroupsResponse
from pyfect.ai.openrouter.generated._schemas_0 import ScimSyncJob as ScimSyncJob
from pyfect.ai.openrouter.generated._schemas_0 import CreateScimSyncJobResponse as CreateScimSyncJobResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetScimSyncJobResponse as GetScimSyncJobResponse
from pyfect.ai.openrouter.generated._schemas_0 import ServerToolOutputName as ServerToolOutputName
from pyfect.ai.openrouter.generated._schemas_0 import ServerToolInputName as ServerToolInputName
from pyfect.ai.openrouter.generated._schemas_0 import ServerToolExecutedBy as ServerToolExecutedBy
from pyfect.ai.openrouter.generated._schemas_0 import ServerToolPrice as ServerToolPrice
from pyfect.ai.openrouter.generated._schemas_0 import ServerToolEngine as ServerToolEngine
from pyfect.ai.openrouter.generated._schemas_0 import ServerToolNativeSupport as ServerToolNativeSupport
from pyfect.ai.openrouter.generated._schemas_0 import ServerTool as ServerTool
from pyfect.ai.openrouter.generated._schemas_0 import ListToolsResponse as ListToolsResponse
from pyfect.ai.openrouter.generated._schemas_0 import ServerToolNativeModel as ServerToolNativeModel
from pyfect.ai.openrouter.generated._schemas_0 import ServerToolDetails as ServerToolDetails
from pyfect.ai.openrouter.generated._schemas_0 import GetToolResponse as GetToolResponse
from pyfect.ai.openrouter.generated._schemas_0 import VaultRoutingTable as VaultRoutingTable
from pyfect.ai.openrouter.generated._schemas_0 import VaultEffectiveSecret as VaultEffectiveSecret
from pyfect.ai.openrouter.generated._schemas_0 import VaultEffectiveSecretListResponse as VaultEffectiveSecretListResponse
from pyfect.ai.openrouter.generated._schemas_0 import VaultSecret as VaultSecret
from pyfect.ai.openrouter.generated._schemas_0 import VaultSecretListResponse as VaultSecretListResponse
from pyfect.ai.openrouter.generated._schemas_0 import VaultSecretWriteRequest as VaultSecretWriteRequest
from pyfect.ai.openrouter.generated._schemas_0 import VaultSecretResponse as VaultSecretResponse
from pyfect.ai.openrouter.generated._schemas_0 import VaultSecretCopyRequest as VaultSecretCopyRequest
from pyfect.ai.openrouter.generated._schemas_0 import VaultSecretCopyResponse as VaultSecretCopyResponse
from pyfect.ai.openrouter.generated._schemas_0 import FrameImage as FrameImage
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartAudio as ContentPartAudio
from pyfect.ai.openrouter.generated._schemas_0 import ContentPartVideo as ContentPartVideo
from pyfect.ai.openrouter.generated._schemas_0 import InputReference as InputReference
from pyfect.ai.openrouter.generated._schemas_0 import VideoGenerationRequest as VideoGenerationRequest
from pyfect.ai.openrouter.generated._schemas_0 import VideoGenerationUsage as VideoGenerationUsage
from pyfect.ai.openrouter.generated._schemas_0 import VideoGenerationResponse as VideoGenerationResponse
from pyfect.ai.openrouter.generated._schemas_0 import VideoModel as VideoModel
from pyfect.ai.openrouter.generated._schemas_0 import VideoModelsListResponse as VideoModelsListResponse
from pyfect.ai.openrouter.generated._schemas_0 import Workspace as Workspace
from pyfect.ai.openrouter.generated._schemas_0 import ListWorkspacesResponse as ListWorkspacesResponse
from pyfect.ai.openrouter.generated._schemas_0 import CreateWorkspaceRequest as CreateWorkspaceRequest
from pyfect.ai.openrouter.generated._schemas_0 import CreateWorkspaceResponse as CreateWorkspaceResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetWorkspaceResponse as GetWorkspaceResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteWorkspaceResponse as DeleteWorkspaceResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpdateWorkspaceRequest as UpdateWorkspaceRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpdateWorkspaceResponse as UpdateWorkspaceResponse
from pyfect.ai.openrouter.generated._schemas_0 import WorkspaceMember as WorkspaceMember
from pyfect.ai.openrouter.generated._schemas_0 import ListWorkspaceMembersResponse as ListWorkspaceMembersResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkAddWorkspaceMembersRequest as BulkAddWorkspaceMembersRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkAddWorkspaceMembersResponse as BulkAddWorkspaceMembersResponse
from pyfect.ai.openrouter.generated._schemas_0 import BulkRemoveWorkspaceMembersRequest as BulkRemoveWorkspaceMembersRequest
from pyfect.ai.openrouter.generated._schemas_0 import BulkRemoveWorkspaceMembersResponse as BulkRemoveWorkspaceMembersResponse
from pyfect.ai.openrouter.generated._schemas_0 import WorkspaceBudget as WorkspaceBudget
from pyfect.ai.openrouter.generated._schemas_0 import ListWorkspaceBudgetsResponse as ListWorkspaceBudgetsResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetWorkspaceBudgetResponse as GetWorkspaceBudgetResponse
from pyfect.ai.openrouter.generated._schemas_0 import UpsertWorkspaceBudgetRequest as UpsertWorkspaceBudgetRequest
from pyfect.ai.openrouter.generated._schemas_0 import UpsertWorkspaceBudgetResponse as UpsertWorkspaceBudgetResponse
from pyfect.ai.openrouter.generated._schemas_0 import DeleteWorkspaceBudgetResponse as DeleteWorkspaceBudgetResponse
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivityParams as GetUserActivityParams
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity200 as GetUserActivity200
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity400 as GetUserActivity400
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity401 as GetUserActivity401
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity403 as GetUserActivity403
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity404 as GetUserActivity404
from pyfect.ai.openrouter.generated._schemas_0 import GetUserActivity500 as GetUserActivity500
from pyfect.ai.openrouter.generated._schemas_0 import GetAnalyticsMetaParams as GetAnalyticsMetaParams
from pyfect.ai.openrouter.generated._schemas_1 import GetAnalyticsMeta200 as GetAnalyticsMeta200
from pyfect.ai.openrouter.generated._schemas_1 import GetAnalyticsMeta401 as GetAnalyticsMeta401
from pyfect.ai.openrouter.generated._schemas_1 import GetAnalyticsMeta403 as GetAnalyticsMeta403
from pyfect.ai.openrouter.generated._schemas_1 import GetAnalyticsMeta500 as GetAnalyticsMeta500
from pyfect.ai.openrouter.generated._schemas_1 import QueryAnalyticsParams as QueryAnalyticsParams
from pyfect.ai.openrouter.generated._schemas_1 import QueryAnalyticsRequestJson as QueryAnalyticsRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import QueryAnalytics200 as QueryAnalytics200
from pyfect.ai.openrouter.generated._schemas_1 import QueryAnalytics400 as QueryAnalytics400
from pyfect.ai.openrouter.generated._schemas_1 import QueryAnalytics401 as QueryAnalytics401
from pyfect.ai.openrouter.generated._schemas_1 import QueryAnalytics403 as QueryAnalytics403
from pyfect.ai.openrouter.generated._schemas_1 import QueryAnalytics408 as QueryAnalytics408
from pyfect.ai.openrouter.generated._schemas_1 import QueryAnalytics500 as QueryAnalytics500
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisionsParams as CreateApiAlphaDecisionsParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisionsRequestJson as CreateApiAlphaDecisionsRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions200 as CreateApiAlphaDecisions200
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions400 as CreateApiAlphaDecisions400
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions401 as CreateApiAlphaDecisions401
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions402 as CreateApiAlphaDecisions402
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions403 as CreateApiAlphaDecisions403
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions404 as CreateApiAlphaDecisions404
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions413 as CreateApiAlphaDecisions413
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions429 as CreateApiAlphaDecisions429
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions500 as CreateApiAlphaDecisions500
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions502 as CreateApiAlphaDecisions502
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions503 as CreateApiAlphaDecisions503
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions524 as CreateApiAlphaDecisions524
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaDecisions529 as CreateApiAlphaDecisions529
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractionsParams as CreateApiAlphaExtractionsParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractionsRequestJson as CreateApiAlphaExtractionsRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions200 as CreateApiAlphaExtractions200
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions400 as CreateApiAlphaExtractions400
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions401 as CreateApiAlphaExtractions401
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions402 as CreateApiAlphaExtractions402
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions403 as CreateApiAlphaExtractions403
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions404 as CreateApiAlphaExtractions404
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions413 as CreateApiAlphaExtractions413
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions429 as CreateApiAlphaExtractions429
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions500 as CreateApiAlphaExtractions500
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions502 as CreateApiAlphaExtractions502
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions503 as CreateApiAlphaExtractions503
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions524 as CreateApiAlphaExtractions524
from pyfect.ai.openrouter.generated._schemas_1 import CreateApiAlphaExtractions529 as CreateApiAlphaExtractions529
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeechParams as CreateAudioSpeechParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeechRequestJson as CreateAudioSpeechRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech400 as CreateAudioSpeech400
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech401 as CreateAudioSpeech401
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech402 as CreateAudioSpeech402
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech403 as CreateAudioSpeech403
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech404 as CreateAudioSpeech404
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech413 as CreateAudioSpeech413
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech429 as CreateAudioSpeech429
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech500 as CreateAudioSpeech500
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech502 as CreateAudioSpeech502
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech503 as CreateAudioSpeech503
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech524 as CreateAudioSpeech524
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioSpeech529 as CreateAudioSpeech529
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptionsParams as CreateAudioTranscriptionsParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptionsRequestJson as CreateAudioTranscriptionsRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions200 as CreateAudioTranscriptions200
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions400 as CreateAudioTranscriptions400
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions401 as CreateAudioTranscriptions401
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions402 as CreateAudioTranscriptions402
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions403 as CreateAudioTranscriptions403
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions404 as CreateAudioTranscriptions404
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions413 as CreateAudioTranscriptions413
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions429 as CreateAudioTranscriptions429
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions500 as CreateAudioTranscriptions500
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions502 as CreateAudioTranscriptions502
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions503 as CreateAudioTranscriptions503
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions504 as CreateAudioTranscriptions504
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions524 as CreateAudioTranscriptions524
from pyfect.ai.openrouter.generated._schemas_1 import CreateAudioTranscriptions529 as CreateAudioTranscriptions529
from pyfect.ai.openrouter.generated._schemas_1 import ExchangeAuthCodeForAPIKeyParams as ExchangeAuthCodeForAPIKeyParams
from pyfect.ai.openrouter.generated._schemas_1 import ExchangeAuthCodeForAPIKeyRequestJson as ExchangeAuthCodeForAPIKeyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import ExchangeAuthCodeForAPIKey200 as ExchangeAuthCodeForAPIKey200
from pyfect.ai.openrouter.generated._schemas_1 import ExchangeAuthCodeForAPIKey400 as ExchangeAuthCodeForAPIKey400
from pyfect.ai.openrouter.generated._schemas_1 import ExchangeAuthCodeForAPIKey403 as ExchangeAuthCodeForAPIKey403
from pyfect.ai.openrouter.generated._schemas_1 import ExchangeAuthCodeForAPIKey500 as ExchangeAuthCodeForAPIKey500
from pyfect.ai.openrouter.generated._schemas_1 import CreateAuthKeysCodeParams as CreateAuthKeysCodeParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateAuthKeysCodeRequestJson as CreateAuthKeysCodeRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateAuthKeysCode200 as CreateAuthKeysCode200
from pyfect.ai.openrouter.generated._schemas_1 import CreateAuthKeysCode400 as CreateAuthKeysCode400
from pyfect.ai.openrouter.generated._schemas_1 import CreateAuthKeysCode401 as CreateAuthKeysCode401
from pyfect.ai.openrouter.generated._schemas_1 import CreateAuthKeysCode403 as CreateAuthKeysCode403
from pyfect.ai.openrouter.generated._schemas_1 import CreateAuthKeysCode409 as CreateAuthKeysCode409
from pyfect.ai.openrouter.generated._schemas_1 import CreateAuthKeysCode500 as CreateAuthKeysCode500
from pyfect.ai.openrouter.generated._schemas_1 import CreateAuthKeysCode503 as CreateAuthKeysCode503
from pyfect.ai.openrouter.generated._schemas_1 import ListBatchesParams as ListBatchesParams
from pyfect.ai.openrouter.generated._schemas_1 import ListBatches200 as ListBatches200
from pyfect.ai.openrouter.generated._schemas_1 import ListBatches400 as ListBatches400
from pyfect.ai.openrouter.generated._schemas_1 import ListBatches401 as ListBatches401
from pyfect.ai.openrouter.generated._schemas_1 import ListBatches429 as ListBatches429
from pyfect.ai.openrouter.generated._schemas_1 import ListBatches500 as ListBatches500
from pyfect.ai.openrouter.generated._schemas_1 import ListBatches502 as ListBatches502
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatchesParams as CreateBatchesParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatchesRequestJson as CreateBatchesRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches202 as CreateBatches202
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches400 as CreateBatches400
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches401 as CreateBatches401
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches402 as CreateBatches402
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches403 as CreateBatches403
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches404 as CreateBatches404
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches413 as CreateBatches413
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches422 as CreateBatches422
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches429 as CreateBatches429
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches500 as CreateBatches500
from pyfect.ai.openrouter.generated._schemas_1 import CreateBatches502 as CreateBatches502
from pyfect.ai.openrouter.generated._schemas_1 import GetBatchesParams as GetBatchesParams
from pyfect.ai.openrouter.generated._schemas_1 import GetBatches200 as GetBatches200
from pyfect.ai.openrouter.generated._schemas_1 import GetBatches401 as GetBatches401
from pyfect.ai.openrouter.generated._schemas_1 import GetBatches402 as GetBatches402
from pyfect.ai.openrouter.generated._schemas_1 import GetBatches404 as GetBatches404
from pyfect.ai.openrouter.generated._schemas_1 import GetBatches410 as GetBatches410
from pyfect.ai.openrouter.generated._schemas_1 import GetBatches429 as GetBatches429
from pyfect.ai.openrouter.generated._schemas_1 import GetBatches500 as GetBatches500
from pyfect.ai.openrouter.generated._schemas_1 import GetBatches502 as GetBatches502
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBatchParams as DeleteBatchParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBatch200 as DeleteBatch200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBatch401 as DeleteBatch401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBatch404 as DeleteBatch404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBatch409 as DeleteBatch409
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBatch429 as DeleteBatch429
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBatch500 as DeleteBatch500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBatch502 as DeleteBatch502
from pyfect.ai.openrouter.generated._schemas_1 import GetBenchmarksParams as GetBenchmarksParams
from pyfect.ai.openrouter.generated._schemas_1 import GetBenchmarks200 as GetBenchmarks200
from pyfect.ai.openrouter.generated._schemas_1 import GetBenchmarks400 as GetBenchmarks400
from pyfect.ai.openrouter.generated._schemas_1 import GetBenchmarks401 as GetBenchmarks401
from pyfect.ai.openrouter.generated._schemas_1 import GetBenchmarks429 as GetBenchmarks429
from pyfect.ai.openrouter.generated._schemas_1 import GetBenchmarks500 as GetBenchmarks500
from pyfect.ai.openrouter.generated._schemas_1 import ListBYOKKeysParams as ListBYOKKeysParams
from pyfect.ai.openrouter.generated._schemas_1 import ListBYOKKeys200 as ListBYOKKeys200
from pyfect.ai.openrouter.generated._schemas_1 import ListBYOKKeys400 as ListBYOKKeys400
from pyfect.ai.openrouter.generated._schemas_1 import ListBYOKKeys401 as ListBYOKKeys401
from pyfect.ai.openrouter.generated._schemas_1 import ListBYOKKeys403 as ListBYOKKeys403
from pyfect.ai.openrouter.generated._schemas_1 import ListBYOKKeys500 as ListBYOKKeys500
from pyfect.ai.openrouter.generated._schemas_1 import CreateBYOKKeyParams as CreateBYOKKeyParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateBYOKKeyRequestJson as CreateBYOKKeyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateBYOKKey201 as CreateBYOKKey201
from pyfect.ai.openrouter.generated._schemas_1 import CreateBYOKKey400 as CreateBYOKKey400
from pyfect.ai.openrouter.generated._schemas_1 import CreateBYOKKey401 as CreateBYOKKey401
from pyfect.ai.openrouter.generated._schemas_1 import CreateBYOKKey403 as CreateBYOKKey403
from pyfect.ai.openrouter.generated._schemas_1 import CreateBYOKKey500 as CreateBYOKKey500
from pyfect.ai.openrouter.generated._schemas_1 import GetBYOKKeyParams as GetBYOKKeyParams
from pyfect.ai.openrouter.generated._schemas_1 import GetBYOKKey200 as GetBYOKKey200
from pyfect.ai.openrouter.generated._schemas_1 import GetBYOKKey401 as GetBYOKKey401
from pyfect.ai.openrouter.generated._schemas_1 import GetBYOKKey403 as GetBYOKKey403
from pyfect.ai.openrouter.generated._schemas_1 import GetBYOKKey404 as GetBYOKKey404
from pyfect.ai.openrouter.generated._schemas_1 import GetBYOKKey500 as GetBYOKKey500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBYOKKeyParams as DeleteBYOKKeyParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBYOKKey200 as DeleteBYOKKey200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBYOKKey401 as DeleteBYOKKey401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBYOKKey403 as DeleteBYOKKey403
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBYOKKey404 as DeleteBYOKKey404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBYOKKey500 as DeleteBYOKKey500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBYOKKeyParams as UpdateBYOKKeyParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBYOKKeyRequestJson as UpdateBYOKKeyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBYOKKey200 as UpdateBYOKKey200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBYOKKey400 as UpdateBYOKKey400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBYOKKey401 as UpdateBYOKKey401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBYOKKey403 as UpdateBYOKKey403
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBYOKKey404 as UpdateBYOKKey404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBYOKKey409 as UpdateBYOKKey409
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBYOKKey500 as UpdateBYOKKey500
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequestParams as SendChatCompletionRequestParams
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequestRequestJson as SendChatCompletionRequestRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest200 as SendChatCompletionRequest200
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest200Sse as SendChatCompletionRequest200Sse
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest400 as SendChatCompletionRequest400
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest401 as SendChatCompletionRequest401
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest402 as SendChatCompletionRequest402
from pyfect.ai.openrouter.generated._schemas_1 import SendChatCompletionRequest403 as SendChatCompletionRequest403
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
from pyfect.ai.openrouter.generated._schemas_1 import ListContainerFilesParams as ListContainerFilesParams
from pyfect.ai.openrouter.generated._schemas_1 import ListContainerFiles200 as ListContainerFiles200
from pyfect.ai.openrouter.generated._schemas_1 import ListContainerFiles400 as ListContainerFiles400
from pyfect.ai.openrouter.generated._schemas_1 import ListContainerFiles401 as ListContainerFiles401
from pyfect.ai.openrouter.generated._schemas_1 import ListContainerFiles403 as ListContainerFiles403
from pyfect.ai.openrouter.generated._schemas_1 import ListContainerFiles429 as ListContainerFiles429
from pyfect.ai.openrouter.generated._schemas_1 import ListContainerFiles500 as ListContainerFiles500
from pyfect.ai.openrouter.generated._schemas_1 import ListContainerFiles503 as ListContainerFiles503
from pyfect.ai.openrouter.generated._schemas_1 import GetContainerFileParams as GetContainerFileParams
from pyfect.ai.openrouter.generated._schemas_1 import GetContainerFile200 as GetContainerFile200
from pyfect.ai.openrouter.generated._schemas_1 import GetContainerFile400 as GetContainerFile400
from pyfect.ai.openrouter.generated._schemas_1 import GetContainerFile401 as GetContainerFile401
from pyfect.ai.openrouter.generated._schemas_1 import GetContainerFile403 as GetContainerFile403
from pyfect.ai.openrouter.generated._schemas_1 import GetContainerFile404 as GetContainerFile404
from pyfect.ai.openrouter.generated._schemas_1 import GetContainerFile429 as GetContainerFile429
from pyfect.ai.openrouter.generated._schemas_1 import GetContainerFile500 as GetContainerFile500
from pyfect.ai.openrouter.generated._schemas_1 import GetContainerFile503 as GetContainerFile503
from pyfect.ai.openrouter.generated._schemas_1 import DownloadContainerFileContentParams as DownloadContainerFileContentParams
from pyfect.ai.openrouter.generated._schemas_1 import DownloadContainerFileContent400 as DownloadContainerFileContent400
from pyfect.ai.openrouter.generated._schemas_1 import DownloadContainerFileContent401 as DownloadContainerFileContent401
from pyfect.ai.openrouter.generated._schemas_1 import DownloadContainerFileContent403 as DownloadContainerFileContent403
from pyfect.ai.openrouter.generated._schemas_1 import DownloadContainerFileContent404 as DownloadContainerFileContent404
from pyfect.ai.openrouter.generated._schemas_1 import DownloadContainerFileContent429 as DownloadContainerFileContent429
from pyfect.ai.openrouter.generated._schemas_1 import DownloadContainerFileContent500 as DownloadContainerFileContent500
from pyfect.ai.openrouter.generated._schemas_1 import DownloadContainerFileContent503 as DownloadContainerFileContent503
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFileParams as PromoteContainerFileParams
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFile200 as PromoteContainerFile200
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFile400 as PromoteContainerFile400
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFile401 as PromoteContainerFile401
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFile403 as PromoteContainerFile403
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFile404 as PromoteContainerFile404
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFile413 as PromoteContainerFile413
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFile429 as PromoteContainerFile429
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFile499 as PromoteContainerFile499
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFile500 as PromoteContainerFile500
from pyfect.ai.openrouter.generated._schemas_1 import PromoteContainerFile503 as PromoteContainerFile503
from pyfect.ai.openrouter.generated._schemas_1 import GetCreditsParams as GetCreditsParams
from pyfect.ai.openrouter.generated._schemas_1 import GetCredits200 as GetCredits200
from pyfect.ai.openrouter.generated._schemas_1 import GetCredits401 as GetCredits401
from pyfect.ai.openrouter.generated._schemas_1 import GetCredits403 as GetCredits403
from pyfect.ai.openrouter.generated._schemas_1 import GetCredits500 as GetCredits500
from pyfect.ai.openrouter.generated._schemas_1 import CreateCoinbaseChargeParams as CreateCoinbaseChargeParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateCoinbaseCharge410 as CreateCoinbaseCharge410
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchasesParams as CreateCreditsPurchasesParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchasesRequestJson as CreateCreditsPurchasesRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchases202 as CreateCreditsPurchases202
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchases400 as CreateCreditsPurchases400
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchases401 as CreateCreditsPurchases401
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchases402 as CreateCreditsPurchases402
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchases403 as CreateCreditsPurchases403
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchases404 as CreateCreditsPurchases404
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchases409 as CreateCreditsPurchases409
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchases429 as CreateCreditsPurchases429
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchases500 as CreateCreditsPurchases500
from pyfect.ai.openrouter.generated._schemas_1 import CreateCreditsPurchases503 as CreateCreditsPurchases503
from pyfect.ai.openrouter.generated._schemas_1 import ListCreditsPurchasesParams as ListCreditsPurchasesParams
from pyfect.ai.openrouter.generated._schemas_1 import ListCreditsPurchases200 as ListCreditsPurchases200
from pyfect.ai.openrouter.generated._schemas_1 import ListCreditsPurchases400 as ListCreditsPurchases400
from pyfect.ai.openrouter.generated._schemas_1 import ListCreditsPurchases401 as ListCreditsPurchases401
from pyfect.ai.openrouter.generated._schemas_1 import ListCreditsPurchases403 as ListCreditsPurchases403
from pyfect.ai.openrouter.generated._schemas_1 import ListCreditsPurchases404 as ListCreditsPurchases404
from pyfect.ai.openrouter.generated._schemas_1 import ListCreditsPurchases429 as ListCreditsPurchases429
from pyfect.ai.openrouter.generated._schemas_1 import ListCreditsPurchases500 as ListCreditsPurchases500
from pyfect.ai.openrouter.generated._schemas_1 import ListCreditsPurchases503 as ListCreditsPurchases503
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
from pyfect.ai.openrouter.generated._schemas_1 import GetSessionCostParams as GetSessionCostParams
from pyfect.ai.openrouter.generated._schemas_1 import GetSessionCost200 as GetSessionCost200
from pyfect.ai.openrouter.generated._schemas_1 import GetSessionCost400 as GetSessionCost400
from pyfect.ai.openrouter.generated._schemas_1 import GetSessionCost401 as GetSessionCost401
from pyfect.ai.openrouter.generated._schemas_1 import GetSessionCost429 as GetSessionCost429
from pyfect.ai.openrouter.generated._schemas_1 import GetSessionCost500 as GetSessionCost500
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddingsParams as CreateEmbeddingsParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddingsRequestJson as CreateEmbeddingsRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings200 as CreateEmbeddings200
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings200Sse as CreateEmbeddings200Sse
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings400 as CreateEmbeddings400
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings401 as CreateEmbeddings401
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings402 as CreateEmbeddings402
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings403 as CreateEmbeddings403
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings404 as CreateEmbeddings404
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings408 as CreateEmbeddings408
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings413 as CreateEmbeddings413
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings429 as CreateEmbeddings429
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings499 as CreateEmbeddings499
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings500 as CreateEmbeddings500
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings502 as CreateEmbeddings502
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings503 as CreateEmbeddings503
from pyfect.ai.openrouter.generated._schemas_1 import CreateEmbeddings504 as CreateEmbeddings504
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
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpointsZdr503 as ListEndpointsZdr503
from pyfect.ai.openrouter.generated._schemas_1 import ListExternalUsersParams as ListExternalUsersParams
from pyfect.ai.openrouter.generated._schemas_1 import ListExternalUsers200 as ListExternalUsers200
from pyfect.ai.openrouter.generated._schemas_1 import ListExternalUsers400 as ListExternalUsers400
from pyfect.ai.openrouter.generated._schemas_1 import ListExternalUsers401 as ListExternalUsers401
from pyfect.ai.openrouter.generated._schemas_1 import ListExternalUsers403 as ListExternalUsers403
from pyfect.ai.openrouter.generated._schemas_1 import ListExternalUsers404 as ListExternalUsers404
from pyfect.ai.openrouter.generated._schemas_1 import ListExternalUsers500 as ListExternalUsers500
from pyfect.ai.openrouter.generated._schemas_1 import CreateExternalUserParams as CreateExternalUserParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateExternalUserRequestJson as CreateExternalUserRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateExternalUser201 as CreateExternalUser201
from pyfect.ai.openrouter.generated._schemas_1 import CreateExternalUser400 as CreateExternalUser400
from pyfect.ai.openrouter.generated._schemas_1 import CreateExternalUser401 as CreateExternalUser401
from pyfect.ai.openrouter.generated._schemas_1 import CreateExternalUser404 as CreateExternalUser404
from pyfect.ai.openrouter.generated._schemas_1 import CreateExternalUser409 as CreateExternalUser409
from pyfect.ai.openrouter.generated._schemas_1 import CreateExternalUser500 as CreateExternalUser500
from pyfect.ai.openrouter.generated._schemas_1 import GetExternalUserParams as GetExternalUserParams
from pyfect.ai.openrouter.generated._schemas_1 import GetExternalUser200 as GetExternalUser200
from pyfect.ai.openrouter.generated._schemas_1 import GetExternalUser400 as GetExternalUser400
from pyfect.ai.openrouter.generated._schemas_1 import GetExternalUser401 as GetExternalUser401
from pyfect.ai.openrouter.generated._schemas_1 import GetExternalUser403 as GetExternalUser403
from pyfect.ai.openrouter.generated._schemas_1 import GetExternalUser404 as GetExternalUser404
from pyfect.ai.openrouter.generated._schemas_1 import GetExternalUser500 as GetExternalUser500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteExternalUserParams as DeleteExternalUserParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteExternalUser400 as DeleteExternalUser400
from pyfect.ai.openrouter.generated._schemas_1 import DeleteExternalUser401 as DeleteExternalUser401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteExternalUser404 as DeleteExternalUser404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteExternalUser500 as DeleteExternalUser500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateExternalUserParams as UpdateExternalUserParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateExternalUserRequestJson as UpdateExternalUserRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateExternalUser200 as UpdateExternalUser200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateExternalUser400 as UpdateExternalUser400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateExternalUser401 as UpdateExternalUser401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateExternalUser404 as UpdateExternalUser404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateExternalUser500 as UpdateExternalUser500
from pyfect.ai.openrouter.generated._schemas_1 import ListFilesParams as ListFilesParams
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles200 as ListFiles200
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles400 as ListFiles400
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles401 as ListFiles401
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles403 as ListFiles403
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles429 as ListFiles429
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles500 as ListFiles500
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles502 as ListFiles502
from pyfect.ai.openrouter.generated._schemas_1 import ListFiles503 as ListFiles503
from pyfect.ai.openrouter.generated._schemas_1 import UploadFileParams as UploadFileParams
from pyfect.ai.openrouter.generated._schemas_1 import UploadFileRequestFormData as UploadFileRequestFormData
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile200 as UploadFile200
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile400 as UploadFile400
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile401 as UploadFile401
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile403 as UploadFile403
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile413 as UploadFile413
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile429 as UploadFile429
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile499 as UploadFile499
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile500 as UploadFile500
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile502 as UploadFile502
from pyfect.ai.openrouter.generated._schemas_1 import UploadFile503 as UploadFile503
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadataParams as GetFileMetadataParams
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata200 as GetFileMetadata200
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata401 as GetFileMetadata401
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata403 as GetFileMetadata403
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata404 as GetFileMetadata404
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata429 as GetFileMetadata429
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata500 as GetFileMetadata500
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata502 as GetFileMetadata502
from pyfect.ai.openrouter.generated._schemas_1 import GetFileMetadata503 as GetFileMetadata503
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFileParams as DeleteFileParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile200 as DeleteFile200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile401 as DeleteFile401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile403 as DeleteFile403
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile404 as DeleteFile404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile429 as DeleteFile429
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile500 as DeleteFile500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile502 as DeleteFile502
from pyfect.ai.openrouter.generated._schemas_1 import DeleteFile503 as DeleteFile503
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContentParams as DownloadFileContentParams
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent400 as DownloadFileContent400
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent401 as DownloadFileContent401
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent403 as DownloadFileContent403
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent404 as DownloadFileContent404
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent429 as DownloadFileContent429
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent500 as DownloadFileContent500
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent502 as DownloadFileContent502
from pyfect.ai.openrouter.generated._schemas_1 import DownloadFileContent503 as DownloadFileContent503
from pyfect.ai.openrouter.generated._schemas_1 import GetGenerationParams as GetGenerationParams
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration200 as GetGeneration200
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration400 as GetGeneration400
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration401 as GetGeneration401
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration402 as GetGeneration402
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration403 as GetGeneration403
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration404 as GetGeneration404
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration429 as GetGeneration429
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration500 as GetGeneration500
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration502 as GetGeneration502
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration524 as GetGeneration524
from pyfect.ai.openrouter.generated._schemas_1 import GetGeneration529 as GetGeneration529
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContentParams as ListGenerationContentParams
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent200 as ListGenerationContent200
from pyfect.ai.openrouter.generated._schemas_1 import ListGenerationContent400 as ListGenerationContent400
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
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback403 as SubmitGenerationFeedback403
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback404 as SubmitGenerationFeedback404
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback409 as SubmitGenerationFeedback409
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback429 as SubmitGenerationFeedback429
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback500 as SubmitGenerationFeedback500
from pyfect.ai.openrouter.generated._schemas_1 import SubmitGenerationFeedback503 as SubmitGenerationFeedback503
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailsParams as ListGuardrailsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrails200 as ListGuardrails200
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrails400 as ListGuardrails400
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrails401 as ListGuardrails401
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrails403 as ListGuardrails403
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
from pyfect.ai.openrouter.generated._schemas_1 import GetGuardrail403 as GetGuardrail403
from pyfect.ai.openrouter.generated._schemas_1 import GetGuardrail404 as GetGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import GetGuardrail500 as GetGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrailParams as DeleteGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrail200 as DeleteGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrail401 as DeleteGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrail403 as DeleteGuardrail403
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrail404 as DeleteGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteGuardrail500 as DeleteGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrailParams as UpdateGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrailRequestJson as UpdateGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail200 as UpdateGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail400 as UpdateGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail401 as UpdateGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail403 as UpdateGuardrail403
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail404 as UpdateGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail409 as UpdateGuardrail409
from pyfect.ai.openrouter.generated._schemas_1 import UpdateGuardrail500 as UpdateGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignmentsParams as ListGuardrailKeyAssignmentsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignments200 as ListGuardrailKeyAssignments200
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignments401 as ListGuardrailKeyAssignments401
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignments403 as ListGuardrailKeyAssignments403
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignments404 as ListGuardrailKeyAssignments404
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailKeyAssignments500 as ListGuardrailKeyAssignments500
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrailParams as BulkAssignKeysToGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrailRequestJson as BulkAssignKeysToGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail200 as BulkAssignKeysToGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail400 as BulkAssignKeysToGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail401 as BulkAssignKeysToGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail403 as BulkAssignKeysToGuardrail403
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail404 as BulkAssignKeysToGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignKeysToGuardrail500 as BulkAssignKeysToGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrailParams as BulkUnassignKeysFromGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrailRequestJson as BulkUnassignKeysFromGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail200 as BulkUnassignKeysFromGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail400 as BulkUnassignKeysFromGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail401 as BulkUnassignKeysFromGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail403 as BulkUnassignKeysFromGuardrail403
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail404 as BulkUnassignKeysFromGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignKeysFromGuardrail500 as BulkUnassignKeysFromGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignmentsParams as ListGuardrailMemberAssignmentsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignments200 as ListGuardrailMemberAssignments200
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignments401 as ListGuardrailMemberAssignments401
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignments403 as ListGuardrailMemberAssignments403
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignments404 as ListGuardrailMemberAssignments404
from pyfect.ai.openrouter.generated._schemas_1 import ListGuardrailMemberAssignments500 as ListGuardrailMemberAssignments500
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrailParams as BulkAssignMembersToGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrailRequestJson as BulkAssignMembersToGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail200 as BulkAssignMembersToGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail400 as BulkAssignMembersToGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail401 as BulkAssignMembersToGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail403 as BulkAssignMembersToGuardrail403
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail404 as BulkAssignMembersToGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import BulkAssignMembersToGuardrail500 as BulkAssignMembersToGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrailParams as BulkUnassignMembersFromGuardrailParams
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrailRequestJson as BulkUnassignMembersFromGuardrailRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail200 as BulkUnassignMembersFromGuardrail200
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail400 as BulkUnassignMembersFromGuardrail400
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail401 as BulkUnassignMembersFromGuardrail401
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail403 as BulkUnassignMembersFromGuardrail403
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail404 as BulkUnassignMembersFromGuardrail404
from pyfect.ai.openrouter.generated._schemas_1 import BulkUnassignMembersFromGuardrail500 as BulkUnassignMembersFromGuardrail500
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignmentsParams as ListKeyAssignmentsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignments200 as ListKeyAssignments200
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignments400 as ListKeyAssignments400
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignments401 as ListKeyAssignments401
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignments403 as ListKeyAssignments403
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignments404 as ListKeyAssignments404
from pyfect.ai.openrouter.generated._schemas_1 import ListKeyAssignments500 as ListKeyAssignments500
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignmentsParams as ListMemberAssignmentsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignments200 as ListMemberAssignments200
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignments400 as ListMemberAssignments400
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignments401 as ListMemberAssignments401
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignments403 as ListMemberAssignments403
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignments404 as ListMemberAssignments404
from pyfect.ai.openrouter.generated._schemas_1 import ListMemberAssignments500 as ListMemberAssignments500
from pyfect.ai.openrouter.generated._schemas_1 import ListAccountPoliciesParams as ListAccountPoliciesParams
from pyfect.ai.openrouter.generated._schemas_1 import ListAccountPolicies200 as ListAccountPolicies200
from pyfect.ai.openrouter.generated._schemas_1 import ListAccountPolicies400 as ListAccountPolicies400
from pyfect.ai.openrouter.generated._schemas_1 import ListAccountPolicies401 as ListAccountPolicies401
from pyfect.ai.openrouter.generated._schemas_1 import ListAccountPolicies403 as ListAccountPolicies403
from pyfect.ai.openrouter.generated._schemas_1 import ListAccountPolicies404 as ListAccountPolicies404
from pyfect.ai.openrouter.generated._schemas_1 import ListAccountPolicies500 as ListAccountPolicies500
from pyfect.ai.openrouter.generated._schemas_1 import CreateAccountPolicyParams as CreateAccountPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateAccountPolicyRequestJson as CreateAccountPolicyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateAccountPolicy201 as CreateAccountPolicy201
from pyfect.ai.openrouter.generated._schemas_1 import CreateAccountPolicy400 as CreateAccountPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import CreateAccountPolicy401 as CreateAccountPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import CreateAccountPolicy403 as CreateAccountPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import CreateAccountPolicy404 as CreateAccountPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import CreateAccountPolicy409 as CreateAccountPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import CreateAccountPolicy500 as CreateAccountPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateAccountPolicyParams as UpdateAccountPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateAccountPolicyRequestJson as UpdateAccountPolicyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateAccountPolicy200 as UpdateAccountPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateAccountPolicy400 as UpdateAccountPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateAccountPolicy401 as UpdateAccountPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateAccountPolicy403 as UpdateAccountPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import UpdateAccountPolicy404 as UpdateAccountPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateAccountPolicy409 as UpdateAccountPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import UpdateAccountPolicy500 as UpdateAccountPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteAccountPolicyParams as DeleteAccountPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteAccountPolicy200 as DeleteAccountPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteAccountPolicy400 as DeleteAccountPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import DeleteAccountPolicy401 as DeleteAccountPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteAccountPolicy403 as DeleteAccountPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import DeleteAccountPolicy404 as DeleteAccountPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteAccountPolicy409 as DeleteAccountPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import DeleteAccountPolicy500 as DeleteAccountPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import GetApiKeyPolicyAssignmentParams as GetApiKeyPolicyAssignmentParams
from pyfect.ai.openrouter.generated._schemas_1 import GetApiKeyPolicyAssignment200 as GetApiKeyPolicyAssignment200
from pyfect.ai.openrouter.generated._schemas_1 import GetApiKeyPolicyAssignment400 as GetApiKeyPolicyAssignment400
from pyfect.ai.openrouter.generated._schemas_1 import GetApiKeyPolicyAssignment401 as GetApiKeyPolicyAssignment401
from pyfect.ai.openrouter.generated._schemas_1 import GetApiKeyPolicyAssignment403 as GetApiKeyPolicyAssignment403
from pyfect.ai.openrouter.generated._schemas_1 import GetApiKeyPolicyAssignment404 as GetApiKeyPolicyAssignment404
from pyfect.ai.openrouter.generated._schemas_1 import GetApiKeyPolicyAssignment500 as GetApiKeyPolicyAssignment500
from pyfect.ai.openrouter.generated._schemas_1 import ChangeApiKeyPolicyAssignmentParams as ChangeApiKeyPolicyAssignmentParams
from pyfect.ai.openrouter.generated._schemas_1 import ChangeApiKeyPolicyAssignmentRequestJson as ChangeApiKeyPolicyAssignmentRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import ChangeApiKeyPolicyAssignment200 as ChangeApiKeyPolicyAssignment200
from pyfect.ai.openrouter.generated._schemas_1 import ChangeApiKeyPolicyAssignment400 as ChangeApiKeyPolicyAssignment400
from pyfect.ai.openrouter.generated._schemas_1 import ChangeApiKeyPolicyAssignment401 as ChangeApiKeyPolicyAssignment401
from pyfect.ai.openrouter.generated._schemas_1 import ChangeApiKeyPolicyAssignment403 as ChangeApiKeyPolicyAssignment403
from pyfect.ai.openrouter.generated._schemas_1 import ChangeApiKeyPolicyAssignment404 as ChangeApiKeyPolicyAssignment404
from pyfect.ai.openrouter.generated._schemas_1 import ChangeApiKeyPolicyAssignment409 as ChangeApiKeyPolicyAssignment409
from pyfect.ai.openrouter.generated._schemas_1 import ChangeApiKeyPolicyAssignment500 as ChangeApiKeyPolicyAssignment500
from pyfect.ai.openrouter.generated._schemas_1 import GetMemberPolicyAssignmentParams as GetMemberPolicyAssignmentParams
from pyfect.ai.openrouter.generated._schemas_1 import GetMemberPolicyAssignment200 as GetMemberPolicyAssignment200
from pyfect.ai.openrouter.generated._schemas_1 import GetMemberPolicyAssignment400 as GetMemberPolicyAssignment400
from pyfect.ai.openrouter.generated._schemas_1 import GetMemberPolicyAssignment401 as GetMemberPolicyAssignment401
from pyfect.ai.openrouter.generated._schemas_1 import GetMemberPolicyAssignment403 as GetMemberPolicyAssignment403
from pyfect.ai.openrouter.generated._schemas_1 import GetMemberPolicyAssignment404 as GetMemberPolicyAssignment404
from pyfect.ai.openrouter.generated._schemas_1 import GetMemberPolicyAssignment500 as GetMemberPolicyAssignment500
from pyfect.ai.openrouter.generated._schemas_1 import ChangeMemberPolicyAssignmentParams as ChangeMemberPolicyAssignmentParams
from pyfect.ai.openrouter.generated._schemas_1 import ChangeMemberPolicyAssignmentRequestJson as ChangeMemberPolicyAssignmentRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import ChangeMemberPolicyAssignment200 as ChangeMemberPolicyAssignment200
from pyfect.ai.openrouter.generated._schemas_1 import ChangeMemberPolicyAssignment400 as ChangeMemberPolicyAssignment400
from pyfect.ai.openrouter.generated._schemas_1 import ChangeMemberPolicyAssignment401 as ChangeMemberPolicyAssignment401
from pyfect.ai.openrouter.generated._schemas_1 import ChangeMemberPolicyAssignment403 as ChangeMemberPolicyAssignment403
from pyfect.ai.openrouter.generated._schemas_1 import ChangeMemberPolicyAssignment404 as ChangeMemberPolicyAssignment404
from pyfect.ai.openrouter.generated._schemas_1 import ChangeMemberPolicyAssignment409 as ChangeMemberPolicyAssignment409
from pyfect.ai.openrouter.generated._schemas_1 import ChangeMemberPolicyAssignment500 as ChangeMemberPolicyAssignment500
from pyfect.ai.openrouter.generated._schemas_1 import ListBudgetPoliciesParams as ListBudgetPoliciesParams
from pyfect.ai.openrouter.generated._schemas_1 import ListBudgetPolicies200 as ListBudgetPolicies200
from pyfect.ai.openrouter.generated._schemas_1 import ListBudgetPolicies400 as ListBudgetPolicies400
from pyfect.ai.openrouter.generated._schemas_1 import ListBudgetPolicies401 as ListBudgetPolicies401
from pyfect.ai.openrouter.generated._schemas_1 import ListBudgetPolicies403 as ListBudgetPolicies403
from pyfect.ai.openrouter.generated._schemas_1 import ListBudgetPolicies404 as ListBudgetPolicies404
from pyfect.ai.openrouter.generated._schemas_1 import ListBudgetPolicies500 as ListBudgetPolicies500
from pyfect.ai.openrouter.generated._schemas_1 import CreateBudgetPolicyParams as CreateBudgetPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateBudgetPolicyRequestJson as CreateBudgetPolicyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateBudgetPolicy201 as CreateBudgetPolicy201
from pyfect.ai.openrouter.generated._schemas_1 import CreateBudgetPolicy400 as CreateBudgetPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import CreateBudgetPolicy401 as CreateBudgetPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import CreateBudgetPolicy403 as CreateBudgetPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import CreateBudgetPolicy404 as CreateBudgetPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import CreateBudgetPolicy409 as CreateBudgetPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import CreateBudgetPolicy500 as CreateBudgetPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import GetBudgetPolicyParams as GetBudgetPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import GetBudgetPolicy200 as GetBudgetPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import GetBudgetPolicy400 as GetBudgetPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import GetBudgetPolicy401 as GetBudgetPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import GetBudgetPolicy403 as GetBudgetPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import GetBudgetPolicy404 as GetBudgetPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import GetBudgetPolicy500 as GetBudgetPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBudgetPolicyParams as UpdateBudgetPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBudgetPolicyRequestJson as UpdateBudgetPolicyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBudgetPolicy200 as UpdateBudgetPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBudgetPolicy400 as UpdateBudgetPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBudgetPolicy401 as UpdateBudgetPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBudgetPolicy403 as UpdateBudgetPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBudgetPolicy404 as UpdateBudgetPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBudgetPolicy409 as UpdateBudgetPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import UpdateBudgetPolicy500 as UpdateBudgetPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBudgetPolicyParams as DeleteBudgetPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBudgetPolicy200 as DeleteBudgetPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBudgetPolicy400 as DeleteBudgetPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBudgetPolicy401 as DeleteBudgetPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBudgetPolicy403 as DeleteBudgetPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBudgetPolicy404 as DeleteBudgetPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBudgetPolicy409 as DeleteBudgetPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import DeleteBudgetPolicy500 as DeleteBudgetPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import ListModelAvailabilityPoliciesParams as ListModelAvailabilityPoliciesParams
from pyfect.ai.openrouter.generated._schemas_1 import ListModelAvailabilityPolicies200 as ListModelAvailabilityPolicies200
from pyfect.ai.openrouter.generated._schemas_1 import ListModelAvailabilityPolicies400 as ListModelAvailabilityPolicies400
from pyfect.ai.openrouter.generated._schemas_1 import ListModelAvailabilityPolicies401 as ListModelAvailabilityPolicies401
from pyfect.ai.openrouter.generated._schemas_1 import ListModelAvailabilityPolicies403 as ListModelAvailabilityPolicies403
from pyfect.ai.openrouter.generated._schemas_1 import ListModelAvailabilityPolicies404 as ListModelAvailabilityPolicies404
from pyfect.ai.openrouter.generated._schemas_1 import ListModelAvailabilityPolicies500 as ListModelAvailabilityPolicies500
from pyfect.ai.openrouter.generated._schemas_1 import CreateModelAvailabilityPolicyParams as CreateModelAvailabilityPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateModelAvailabilityPolicyRequestJson as CreateModelAvailabilityPolicyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateModelAvailabilityPolicy201 as CreateModelAvailabilityPolicy201
from pyfect.ai.openrouter.generated._schemas_1 import CreateModelAvailabilityPolicy400 as CreateModelAvailabilityPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import CreateModelAvailabilityPolicy401 as CreateModelAvailabilityPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import CreateModelAvailabilityPolicy403 as CreateModelAvailabilityPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import CreateModelAvailabilityPolicy404 as CreateModelAvailabilityPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import CreateModelAvailabilityPolicy409 as CreateModelAvailabilityPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import CreateModelAvailabilityPolicy500 as CreateModelAvailabilityPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import GetModelAvailabilityPolicyParams as GetModelAvailabilityPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import GetModelAvailabilityPolicy200 as GetModelAvailabilityPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import GetModelAvailabilityPolicy400 as GetModelAvailabilityPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import GetModelAvailabilityPolicy401 as GetModelAvailabilityPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import GetModelAvailabilityPolicy403 as GetModelAvailabilityPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import GetModelAvailabilityPolicy404 as GetModelAvailabilityPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import GetModelAvailabilityPolicy500 as GetModelAvailabilityPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModelAvailabilityPolicyParams as UpdateModelAvailabilityPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModelAvailabilityPolicyRequestJson as UpdateModelAvailabilityPolicyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModelAvailabilityPolicy200 as UpdateModelAvailabilityPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModelAvailabilityPolicy400 as UpdateModelAvailabilityPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModelAvailabilityPolicy401 as UpdateModelAvailabilityPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModelAvailabilityPolicy403 as UpdateModelAvailabilityPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModelAvailabilityPolicy404 as UpdateModelAvailabilityPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModelAvailabilityPolicy409 as UpdateModelAvailabilityPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModelAvailabilityPolicy500 as UpdateModelAvailabilityPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModelAvailabilityPolicyParams as DeleteModelAvailabilityPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModelAvailabilityPolicy200 as DeleteModelAvailabilityPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModelAvailabilityPolicy400 as DeleteModelAvailabilityPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModelAvailabilityPolicy401 as DeleteModelAvailabilityPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModelAvailabilityPolicy403 as DeleteModelAvailabilityPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModelAvailabilityPolicy404 as DeleteModelAvailabilityPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModelAvailabilityPolicy409 as DeleteModelAvailabilityPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModelAvailabilityPolicy500 as DeleteModelAvailabilityPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import ListModerationPoliciesParams as ListModerationPoliciesParams
from pyfect.ai.openrouter.generated._schemas_1 import ListModerationPolicies200 as ListModerationPolicies200
from pyfect.ai.openrouter.generated._schemas_1 import ListModerationPolicies400 as ListModerationPolicies400
from pyfect.ai.openrouter.generated._schemas_1 import ListModerationPolicies401 as ListModerationPolicies401
from pyfect.ai.openrouter.generated._schemas_1 import ListModerationPolicies403 as ListModerationPolicies403
from pyfect.ai.openrouter.generated._schemas_1 import ListModerationPolicies404 as ListModerationPolicies404
from pyfect.ai.openrouter.generated._schemas_1 import ListModerationPolicies500 as ListModerationPolicies500
from pyfect.ai.openrouter.generated._schemas_1 import CreateModerationPolicyParams as CreateModerationPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateModerationPolicyRequestJson as CreateModerationPolicyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreateModerationPolicy201 as CreateModerationPolicy201
from pyfect.ai.openrouter.generated._schemas_1 import CreateModerationPolicy400 as CreateModerationPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import CreateModerationPolicy401 as CreateModerationPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import CreateModerationPolicy403 as CreateModerationPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import CreateModerationPolicy404 as CreateModerationPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import CreateModerationPolicy409 as CreateModerationPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import CreateModerationPolicy500 as CreateModerationPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import GetModerationPolicyParams as GetModerationPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import GetModerationPolicy200 as GetModerationPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import GetModerationPolicy400 as GetModerationPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import GetModerationPolicy401 as GetModerationPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import GetModerationPolicy403 as GetModerationPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import GetModerationPolicy404 as GetModerationPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import GetModerationPolicy500 as GetModerationPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModerationPolicyParams as UpdateModerationPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModerationPolicyRequestJson as UpdateModerationPolicyRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModerationPolicy200 as UpdateModerationPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModerationPolicy400 as UpdateModerationPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModerationPolicy401 as UpdateModerationPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModerationPolicy403 as UpdateModerationPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModerationPolicy404 as UpdateModerationPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModerationPolicy409 as UpdateModerationPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import UpdateModerationPolicy500 as UpdateModerationPolicy500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModerationPolicyParams as DeleteModerationPolicyParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModerationPolicy200 as DeleteModerationPolicy200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModerationPolicy400 as DeleteModerationPolicy400
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModerationPolicy401 as DeleteModerationPolicy401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModerationPolicy403 as DeleteModerationPolicy403
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModerationPolicy404 as DeleteModerationPolicy404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModerationPolicy409 as DeleteModerationPolicy409
from pyfect.ai.openrouter.generated._schemas_1 import DeleteModerationPolicy500 as DeleteModerationPolicy500
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
from pyfect.ai.openrouter.generated._schemas_1 import List403 as List403
from pyfect.ai.openrouter.generated._schemas_1 import List404 as List404
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
from pyfect.ai.openrouter.generated._schemas_1 import GetKey403 as GetKey403
from pyfect.ai.openrouter.generated._schemas_1 import GetKey404 as GetKey404
from pyfect.ai.openrouter.generated._schemas_1 import GetKey429 as GetKey429
from pyfect.ai.openrouter.generated._schemas_1 import GetKey500 as GetKey500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeysParams as DeleteKeysParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys200 as DeleteKeys200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys401 as DeleteKeys401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys403 as DeleteKeys403
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys404 as DeleteKeys404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys429 as DeleteKeys429
from pyfect.ai.openrouter.generated._schemas_1 import DeleteKeys500 as DeleteKeys500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeysParams as UpdateKeysParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeysRequestJson as UpdateKeysRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys200 as UpdateKeys200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys400 as UpdateKeys400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys401 as UpdateKeys401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys403 as UpdateKeys403
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys404 as UpdateKeys404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateKeys409 as UpdateKeys409
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
from pyfect.ai.openrouter.generated._schemas_1 import GetModels401 as GetModels401
from pyfect.ai.openrouter.generated._schemas_1 import GetModels403 as GetModels403
from pyfect.ai.openrouter.generated._schemas_1 import GetModels404 as GetModels404
from pyfect.ai.openrouter.generated._schemas_1 import GetModels408 as GetModels408
from pyfect.ai.openrouter.generated._schemas_1 import GetModels409 as GetModels409
from pyfect.ai.openrouter.generated._schemas_1 import GetModels429 as GetModels429
from pyfect.ai.openrouter.generated._schemas_1 import GetModels500 as GetModels500
from pyfect.ai.openrouter.generated._schemas_1 import GetModels503 as GetModels503
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpointsParams as ListEndpointsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpoints200 as ListEndpoints200
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpoints403 as ListEndpoints403
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpoints404 as ListEndpoints404
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpoints500 as ListEndpoints500
from pyfect.ai.openrouter.generated._schemas_1 import ListEndpoints503 as ListEndpoints503
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
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUser408 as ListModelsUser408
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUser409 as ListModelsUser409
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUser429 as ListModelsUser429
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUser500 as ListModelsUser500
from pyfect.ai.openrouter.generated._schemas_1 import ListModelsUser503 as ListModelsUser503
from pyfect.ai.openrouter.generated._schemas_1 import ListOauthJwksParams as ListOauthJwksParams
from pyfect.ai.openrouter.generated._schemas_1 import ListOauthJwks200 as ListOauthJwks200
from pyfect.ai.openrouter.generated._schemas_1 import ListOauthJwks500 as ListOauthJwks500
from pyfect.ai.openrouter.generated._schemas_1 import CreateOauthTokenParams as CreateOauthTokenParams
from pyfect.ai.openrouter.generated._schemas_1 import CreateOauthTokenRequestFormUrlEncoded as CreateOauthTokenRequestFormUrlEncoded
from pyfect.ai.openrouter.generated._schemas_1 import CreateOauthToken200 as CreateOauthToken200
from pyfect.ai.openrouter.generated._schemas_1 import CreateOauthToken400 as CreateOauthToken400
from pyfect.ai.openrouter.generated._schemas_1 import CreateOauthToken429 as CreateOauthToken429
from pyfect.ai.openrouter.generated._schemas_1 import CreateOauthToken500 as CreateOauthToken500
from pyfect.ai.openrouter.generated._schemas_1 import CreateOauthToken503 as CreateOauthToken503
from pyfect.ai.openrouter.generated._schemas_1 import ListObservabilityDestinationsParams as ListObservabilityDestinationsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListObservabilityDestinations200 as ListObservabilityDestinations200
from pyfect.ai.openrouter.generated._schemas_1 import ListObservabilityDestinations400 as ListObservabilityDestinations400
from pyfect.ai.openrouter.generated._schemas_1 import ListObservabilityDestinations401 as ListObservabilityDestinations401
from pyfect.ai.openrouter.generated._schemas_1 import ListObservabilityDestinations403 as ListObservabilityDestinations403
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
from pyfect.ai.openrouter.generated._schemas_1 import GetObservabilityDestination403 as GetObservabilityDestination403
from pyfect.ai.openrouter.generated._schemas_1 import GetObservabilityDestination404 as GetObservabilityDestination404
from pyfect.ai.openrouter.generated._schemas_1 import GetObservabilityDestination500 as GetObservabilityDestination500
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestinationParams as DeleteObservabilityDestinationParams
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestination200 as DeleteObservabilityDestination200
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestination401 as DeleteObservabilityDestination401
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestination403 as DeleteObservabilityDestination403
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestination404 as DeleteObservabilityDestination404
from pyfect.ai.openrouter.generated._schemas_1 import DeleteObservabilityDestination500 as DeleteObservabilityDestination500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestinationParams as UpdateObservabilityDestinationParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestinationRequestJson as UpdateObservabilityDestinationRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination200 as UpdateObservabilityDestination200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination400 as UpdateObservabilityDestination400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination401 as UpdateObservabilityDestination401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination403 as UpdateObservabilityDestination403
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination404 as UpdateObservabilityDestination404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination409 as UpdateObservabilityDestination409
from pyfect.ai.openrouter.generated._schemas_1 import UpdateObservabilityDestination500 as UpdateObservabilityDestination500
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembersParams as ListOrganizationMembersParams
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembers200 as ListOrganizationMembers200
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembers401 as ListOrganizationMembers401
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembers403 as ListOrganizationMembers403
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembers404 as ListOrganizationMembers404
from pyfect.ai.openrouter.generated._schemas_1 import ListOrganizationMembers500 as ListOrganizationMembers500
from pyfect.ai.openrouter.generated._schemas_1 import GetOrganizationSettingsParams as GetOrganizationSettingsParams
from pyfect.ai.openrouter.generated._schemas_1 import GetOrganizationSettings200 as GetOrganizationSettings200
from pyfect.ai.openrouter.generated._schemas_1 import GetOrganizationSettings401 as GetOrganizationSettings401
from pyfect.ai.openrouter.generated._schemas_1 import GetOrganizationSettings403 as GetOrganizationSettings403
from pyfect.ai.openrouter.generated._schemas_1 import GetOrganizationSettings404 as GetOrganizationSettings404
from pyfect.ai.openrouter.generated._schemas_1 import GetOrganizationSettings500 as GetOrganizationSettings500
from pyfect.ai.openrouter.generated._schemas_1 import UpdateOrganizationSettingsParams as UpdateOrganizationSettingsParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdateOrganizationSettingsRequestJson as UpdateOrganizationSettingsRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdateOrganizationSettings200 as UpdateOrganizationSettings200
from pyfect.ai.openrouter.generated._schemas_1 import UpdateOrganizationSettings400 as UpdateOrganizationSettings400
from pyfect.ai.openrouter.generated._schemas_1 import UpdateOrganizationSettings401 as UpdateOrganizationSettings401
from pyfect.ai.openrouter.generated._schemas_1 import UpdateOrganizationSettings403 as UpdateOrganizationSettings403
from pyfect.ai.openrouter.generated._schemas_1 import UpdateOrganizationSettings404 as UpdateOrganizationSettings404
from pyfect.ai.openrouter.generated._schemas_1 import UpdateOrganizationSettings500 as UpdateOrganizationSettings500
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetsParams as ListPresetsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets200 as ListPresets200
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets400 as ListPresets400
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets401 as ListPresets401
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets403 as ListPresets403
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets404 as ListPresets404
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets500 as ListPresets500
from pyfect.ai.openrouter.generated._schemas_1 import ListPresets503 as ListPresets503
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetParams as GetPresetParams
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset200 as GetPreset200
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset400 as GetPreset400
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset401 as GetPreset401
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset403 as GetPreset403
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset404 as GetPreset404
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset500 as GetPreset500
from pyfect.ai.openrouter.generated._schemas_1 import GetPreset503 as GetPreset503
from pyfect.ai.openrouter.generated._schemas_1 import DeletePresetParams as DeletePresetParams
from pyfect.ai.openrouter.generated._schemas_1 import DeletePreset200 as DeletePreset200
from pyfect.ai.openrouter.generated._schemas_1 import DeletePreset400 as DeletePreset400
from pyfect.ai.openrouter.generated._schemas_1 import DeletePreset401 as DeletePreset401
from pyfect.ai.openrouter.generated._schemas_1 import DeletePreset403 as DeletePreset403
from pyfect.ai.openrouter.generated._schemas_1 import DeletePreset404 as DeletePreset404
from pyfect.ai.openrouter.generated._schemas_1 import DeletePreset409 as DeletePreset409
from pyfect.ai.openrouter.generated._schemas_1 import DeletePreset500 as DeletePreset500
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
from pyfect.ai.openrouter.generated._schemas_1 import RestorePresetParams as RestorePresetParams
from pyfect.ai.openrouter.generated._schemas_1 import RestorePreset200 as RestorePreset200
from pyfect.ai.openrouter.generated._schemas_1 import RestorePreset400 as RestorePreset400
from pyfect.ai.openrouter.generated._schemas_1 import RestorePreset401 as RestorePreset401
from pyfect.ai.openrouter.generated._schemas_1 import RestorePreset403 as RestorePreset403
from pyfect.ai.openrouter.generated._schemas_1 import RestorePreset404 as RestorePreset404
from pyfect.ai.openrouter.generated._schemas_1 import RestorePreset409 as RestorePreset409
from pyfect.ai.openrouter.generated._schemas_1 import RestorePreset500 as RestorePreset500
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersionsParams as ListPresetVersionsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions200 as ListPresetVersions200
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions400 as ListPresetVersions400
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions401 as ListPresetVersions401
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions403 as ListPresetVersions403
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions404 as ListPresetVersions404
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions500 as ListPresetVersions500
from pyfect.ai.openrouter.generated._schemas_1 import ListPresetVersions503 as ListPresetVersions503
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersionParams as GetPresetVersionParams
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion200 as GetPresetVersion200
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion400 as GetPresetVersion400
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion401 as GetPresetVersion401
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion403 as GetPresetVersion403
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion404 as GetPresetVersion404
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion500 as GetPresetVersion500
from pyfect.ai.openrouter.generated._schemas_1 import GetPresetVersion503 as GetPresetVersion503
from pyfect.ai.openrouter.generated._schemas_1 import ListPrivateEndpointsParams as ListPrivateEndpointsParams
from pyfect.ai.openrouter.generated._schemas_1 import ListPrivateEndpoints200 as ListPrivateEndpoints200
from pyfect.ai.openrouter.generated._schemas_1 import ListPrivateEndpoints401 as ListPrivateEndpoints401
from pyfect.ai.openrouter.generated._schemas_1 import ListPrivateEndpoints403 as ListPrivateEndpoints403
from pyfect.ai.openrouter.generated._schemas_1 import ListPrivateEndpoints408 as ListPrivateEndpoints408
from pyfect.ai.openrouter.generated._schemas_1 import ListPrivateEndpoints500 as ListPrivateEndpoints500
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpointParams as CreatePrivateEndpointParams
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpointRequestJson as CreatePrivateEndpointRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpoint201 as CreatePrivateEndpoint201
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpoint400 as CreatePrivateEndpoint400
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpoint401 as CreatePrivateEndpoint401
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpoint403 as CreatePrivateEndpoint403
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpoint404 as CreatePrivateEndpoint404
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpoint408 as CreatePrivateEndpoint408
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpoint409 as CreatePrivateEndpoint409
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpoint422 as CreatePrivateEndpoint422
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpoint500 as CreatePrivateEndpoint500
from pyfect.ai.openrouter.generated._schemas_1 import CreatePrivateEndpoint502 as CreatePrivateEndpoint502
from pyfect.ai.openrouter.generated._schemas_1 import GetPrivateEndpointParams as GetPrivateEndpointParams
from pyfect.ai.openrouter.generated._schemas_1 import GetPrivateEndpoint200 as GetPrivateEndpoint200
from pyfect.ai.openrouter.generated._schemas_1 import GetPrivateEndpoint401 as GetPrivateEndpoint401
from pyfect.ai.openrouter.generated._schemas_1 import GetPrivateEndpoint403 as GetPrivateEndpoint403
from pyfect.ai.openrouter.generated._schemas_1 import GetPrivateEndpoint404 as GetPrivateEndpoint404
from pyfect.ai.openrouter.generated._schemas_1 import GetPrivateEndpoint408 as GetPrivateEndpoint408
from pyfect.ai.openrouter.generated._schemas_1 import GetPrivateEndpoint500 as GetPrivateEndpoint500
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpointParams as DeletePrivateEndpointParams
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpoint200 as DeletePrivateEndpoint200
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpoint400 as DeletePrivateEndpoint400
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpoint401 as DeletePrivateEndpoint401
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpoint403 as DeletePrivateEndpoint403
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpoint404 as DeletePrivateEndpoint404
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpoint408 as DeletePrivateEndpoint408
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpoint409 as DeletePrivateEndpoint409
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpoint422 as DeletePrivateEndpoint422
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpoint500 as DeletePrivateEndpoint500
from pyfect.ai.openrouter.generated._schemas_1 import DeletePrivateEndpoint502 as DeletePrivateEndpoint502
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpointParams as UpdatePrivateEndpointParams
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpointRequestJson as UpdatePrivateEndpointRequestJson
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpoint200 as UpdatePrivateEndpoint200
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpoint400 as UpdatePrivateEndpoint400
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpoint401 as UpdatePrivateEndpoint401
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpoint403 as UpdatePrivateEndpoint403
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpoint404 as UpdatePrivateEndpoint404
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpoint408 as UpdatePrivateEndpoint408
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpoint409 as UpdatePrivateEndpoint409
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpoint422 as UpdatePrivateEndpoint422
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpoint500 as UpdatePrivateEndpoint500
from pyfect.ai.openrouter.generated._schemas_1 import UpdatePrivateEndpoint502 as UpdatePrivateEndpoint502
from pyfect.ai.openrouter.generated._schemas_1 import ActivatePrivateEndpointParams as ActivatePrivateEndpointParams
from pyfect.ai.openrouter.generated._schemas_1 import ActivatePrivateEndpoint200 as ActivatePrivateEndpoint200
from pyfect.ai.openrouter.generated._schemas_1 import ActivatePrivateEndpoint400 as ActivatePrivateEndpoint400
from pyfect.ai.openrouter.generated._schemas_1 import ActivatePrivateEndpoint401 as ActivatePrivateEndpoint401
from pyfect.ai.openrouter.generated._schemas_1 import ActivatePrivateEndpoint403 as ActivatePrivateEndpoint403
from pyfect.ai.openrouter.generated._schemas_1 import ActivatePrivateEndpoint404 as ActivatePrivateEndpoint404
from pyfect.ai.openrouter.generated._schemas_2 import ActivatePrivateEndpoint408 as ActivatePrivateEndpoint408
from pyfect.ai.openrouter.generated._schemas_2 import ActivatePrivateEndpoint409 as ActivatePrivateEndpoint409
from pyfect.ai.openrouter.generated._schemas_2 import ActivatePrivateEndpoint422 as ActivatePrivateEndpoint422
from pyfect.ai.openrouter.generated._schemas_2 import ActivatePrivateEndpoint500 as ActivatePrivateEndpoint500
from pyfect.ai.openrouter.generated._schemas_2 import ActivatePrivateEndpoint502 as ActivatePrivateEndpoint502
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpointParams as DisablePrivateEndpointParams
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpoint200 as DisablePrivateEndpoint200
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpoint400 as DisablePrivateEndpoint400
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpoint401 as DisablePrivateEndpoint401
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpoint403 as DisablePrivateEndpoint403
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpoint404 as DisablePrivateEndpoint404
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpoint408 as DisablePrivateEndpoint408
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpoint409 as DisablePrivateEndpoint409
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpoint422 as DisablePrivateEndpoint422
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpoint500 as DisablePrivateEndpoint500
from pyfect.ai.openrouter.generated._schemas_2 import DisablePrivateEndpoint502 as DisablePrivateEndpoint502
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpointParams as EnablePrivateEndpointParams
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpoint200 as EnablePrivateEndpoint200
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpoint400 as EnablePrivateEndpoint400
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpoint401 as EnablePrivateEndpoint401
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpoint403 as EnablePrivateEndpoint403
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpoint404 as EnablePrivateEndpoint404
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpoint408 as EnablePrivateEndpoint408
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpoint409 as EnablePrivateEndpoint409
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpoint422 as EnablePrivateEndpoint422
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpoint500 as EnablePrivateEndpoint500
from pyfect.ai.openrouter.generated._schemas_2 import EnablePrivateEndpoint502 as EnablePrivateEndpoint502
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpointParams as ValidatePrivateEndpointParams
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpointRequestJson as ValidatePrivateEndpointRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpoint200 as ValidatePrivateEndpoint200
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpoint400 as ValidatePrivateEndpoint400
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpoint401 as ValidatePrivateEndpoint401
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpoint403 as ValidatePrivateEndpoint403
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpoint404 as ValidatePrivateEndpoint404
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpoint408 as ValidatePrivateEndpoint408
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpoint409 as ValidatePrivateEndpoint409
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpoint422 as ValidatePrivateEndpoint422
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpoint500 as ValidatePrivateEndpoint500
from pyfect.ai.openrouter.generated._schemas_2 import ValidatePrivateEndpoint502 as ValidatePrivateEndpoint502
from pyfect.ai.openrouter.generated._schemas_2 import ListPrivateProvidersParams as ListPrivateProvidersParams
from pyfect.ai.openrouter.generated._schemas_2 import ListPrivateProviders200 as ListPrivateProviders200
from pyfect.ai.openrouter.generated._schemas_2 import ListPrivateProviders401 as ListPrivateProviders401
from pyfect.ai.openrouter.generated._schemas_2 import ListPrivateProviders403 as ListPrivateProviders403
from pyfect.ai.openrouter.generated._schemas_2 import ListPrivateProviders500 as ListPrivateProviders500
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProviderParams as CreatePrivateProviderParams
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProviderRequestJson as CreatePrivateProviderRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider201 as CreatePrivateProvider201
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider400 as CreatePrivateProvider400
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider401 as CreatePrivateProvider401
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider403 as CreatePrivateProvider403
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider404 as CreatePrivateProvider404
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider408 as CreatePrivateProvider408
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider409 as CreatePrivateProvider409
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider422 as CreatePrivateProvider422
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider429 as CreatePrivateProvider429
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider500 as CreatePrivateProvider500
from pyfect.ai.openrouter.generated._schemas_2 import CreatePrivateProvider502 as CreatePrivateProvider502
from pyfect.ai.openrouter.generated._schemas_2 import GetPrivateProviderParams as GetPrivateProviderParams
from pyfect.ai.openrouter.generated._schemas_2 import GetPrivateProvider200 as GetPrivateProvider200
from pyfect.ai.openrouter.generated._schemas_2 import GetPrivateProvider401 as GetPrivateProvider401
from pyfect.ai.openrouter.generated._schemas_2 import GetPrivateProvider403 as GetPrivateProvider403
from pyfect.ai.openrouter.generated._schemas_2 import GetPrivateProvider404 as GetPrivateProvider404
from pyfect.ai.openrouter.generated._schemas_2 import GetPrivateProvider500 as GetPrivateProvider500
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProviderParams as DeletePrivateProviderParams
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider200 as DeletePrivateProvider200
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider400 as DeletePrivateProvider400
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider401 as DeletePrivateProvider401
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider403 as DeletePrivateProvider403
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider404 as DeletePrivateProvider404
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider408 as DeletePrivateProvider408
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider409 as DeletePrivateProvider409
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider422 as DeletePrivateProvider422
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider429 as DeletePrivateProvider429
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider500 as DeletePrivateProvider500
from pyfect.ai.openrouter.generated._schemas_2 import DeletePrivateProvider502 as DeletePrivateProvider502
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProviderParams as UpdatePrivateProviderParams
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProviderRequestJson as UpdatePrivateProviderRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider200 as UpdatePrivateProvider200
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider400 as UpdatePrivateProvider400
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider401 as UpdatePrivateProvider401
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider403 as UpdatePrivateProvider403
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider404 as UpdatePrivateProvider404
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider408 as UpdatePrivateProvider408
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider409 as UpdatePrivateProvider409
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider422 as UpdatePrivateProvider422
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider429 as UpdatePrivateProvider429
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider500 as UpdatePrivateProvider500
from pyfect.ai.openrouter.generated._schemas_2 import UpdatePrivateProvider502 as UpdatePrivateProvider502
from pyfect.ai.openrouter.generated._schemas_2 import ListProvidersParams as ListProvidersParams
from pyfect.ai.openrouter.generated._schemas_2 import ListProviders200 as ListProviders200
from pyfect.ai.openrouter.generated._schemas_2 import ListProviders500 as ListProviders500
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerankParams as CreateRerankParams
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerankRequestJson as CreateRerankRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank200 as CreateRerank200
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank200Sse as CreateRerank200Sse
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank400 as CreateRerank400
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank401 as CreateRerank401
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank402 as CreateRerank402
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank403 as CreateRerank403
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank404 as CreateRerank404
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank413 as CreateRerank413
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank429 as CreateRerank429
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank500 as CreateRerank500
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank502 as CreateRerank502
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank503 as CreateRerank503
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank524 as CreateRerank524
from pyfect.ai.openrouter.generated._schemas_2 import CreateRerank529 as CreateRerank529
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponsesParams as CreateResponsesParams
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponsesRequestJson as CreateResponsesRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses200 as CreateResponses200
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses200Sse as CreateResponses200Sse
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses400 as CreateResponses400
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses401 as CreateResponses401
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses402 as CreateResponses402
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses403 as CreateResponses403
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses404 as CreateResponses404
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses408 as CreateResponses408
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses413 as CreateResponses413
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses422 as CreateResponses422
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses429 as CreateResponses429
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses500 as CreateResponses500
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses502 as CreateResponses502
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses503 as CreateResponses503
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses524 as CreateResponses524
from pyfect.ai.openrouter.generated._schemas_2 import CreateResponses529 as CreateResponses529
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroupMappingsParams as ListScimGroupMappingsParams
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroupMappings200 as ListScimGroupMappings200
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroupMappings401 as ListScimGroupMappings401
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroupMappings403 as ListScimGroupMappings403
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroupMappings404 as ListScimGroupMappings404
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroupMappings500 as ListScimGroupMappings500
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimGroupMappingParams as CreateScimGroupMappingParams
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimGroupMappingRequestJson as CreateScimGroupMappingRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimGroupMapping201 as CreateScimGroupMapping201
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimGroupMapping400 as CreateScimGroupMapping400
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimGroupMapping401 as CreateScimGroupMapping401
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimGroupMapping403 as CreateScimGroupMapping403
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimGroupMapping404 as CreateScimGroupMapping404
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimGroupMapping409 as CreateScimGroupMapping409
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimGroupMapping500 as CreateScimGroupMapping500
from pyfect.ai.openrouter.generated._schemas_2 import GetScimGroupMappingParams as GetScimGroupMappingParams
from pyfect.ai.openrouter.generated._schemas_2 import GetScimGroupMapping200 as GetScimGroupMapping200
from pyfect.ai.openrouter.generated._schemas_2 import GetScimGroupMapping401 as GetScimGroupMapping401
from pyfect.ai.openrouter.generated._schemas_2 import GetScimGroupMapping403 as GetScimGroupMapping403
from pyfect.ai.openrouter.generated._schemas_2 import GetScimGroupMapping404 as GetScimGroupMapping404
from pyfect.ai.openrouter.generated._schemas_2 import GetScimGroupMapping500 as GetScimGroupMapping500
from pyfect.ai.openrouter.generated._schemas_2 import DeleteScimGroupMappingParams as DeleteScimGroupMappingParams
from pyfect.ai.openrouter.generated._schemas_2 import DeleteScimGroupMapping200 as DeleteScimGroupMapping200
from pyfect.ai.openrouter.generated._schemas_2 import DeleteScimGroupMapping400 as DeleteScimGroupMapping400
from pyfect.ai.openrouter.generated._schemas_2 import DeleteScimGroupMapping401 as DeleteScimGroupMapping401
from pyfect.ai.openrouter.generated._schemas_2 import DeleteScimGroupMapping403 as DeleteScimGroupMapping403
from pyfect.ai.openrouter.generated._schemas_2 import DeleteScimGroupMapping404 as DeleteScimGroupMapping404
from pyfect.ai.openrouter.generated._schemas_2 import DeleteScimGroupMapping500 as DeleteScimGroupMapping500
from pyfect.ai.openrouter.generated._schemas_2 import UpdateScimGroupMappingParams as UpdateScimGroupMappingParams
from pyfect.ai.openrouter.generated._schemas_2 import UpdateScimGroupMappingRequestJson as UpdateScimGroupMappingRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import UpdateScimGroupMapping200 as UpdateScimGroupMapping200
from pyfect.ai.openrouter.generated._schemas_2 import UpdateScimGroupMapping400 as UpdateScimGroupMapping400
from pyfect.ai.openrouter.generated._schemas_2 import UpdateScimGroupMapping401 as UpdateScimGroupMapping401
from pyfect.ai.openrouter.generated._schemas_2 import UpdateScimGroupMapping403 as UpdateScimGroupMapping403
from pyfect.ai.openrouter.generated._schemas_2 import UpdateScimGroupMapping404 as UpdateScimGroupMapping404
from pyfect.ai.openrouter.generated._schemas_2 import UpdateScimGroupMapping500 as UpdateScimGroupMapping500
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroupsParams as ListScimGroupsParams
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroups200 as ListScimGroups200
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroups401 as ListScimGroups401
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroups403 as ListScimGroups403
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroups404 as ListScimGroups404
from pyfect.ai.openrouter.generated._schemas_2 import ListScimGroups500 as ListScimGroups500
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimSyncJobParams as CreateScimSyncJobParams
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimSyncJob202 as CreateScimSyncJob202
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimSyncJob401 as CreateScimSyncJob401
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimSyncJob403 as CreateScimSyncJob403
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimSyncJob404 as CreateScimSyncJob404
from pyfect.ai.openrouter.generated._schemas_2 import CreateScimSyncJob500 as CreateScimSyncJob500
from pyfect.ai.openrouter.generated._schemas_2 import GetScimSyncJobParams as GetScimSyncJobParams
from pyfect.ai.openrouter.generated._schemas_2 import GetScimSyncJob200 as GetScimSyncJob200
from pyfect.ai.openrouter.generated._schemas_2 import GetScimSyncJob401 as GetScimSyncJob401
from pyfect.ai.openrouter.generated._schemas_2 import GetScimSyncJob403 as GetScimSyncJob403
from pyfect.ai.openrouter.generated._schemas_2 import GetScimSyncJob404 as GetScimSyncJob404
from pyfect.ai.openrouter.generated._schemas_2 import GetScimSyncJob500 as GetScimSyncJob500
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemoneParams as CreateSystemoneParams
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemoneRequestJson as CreateSystemoneRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone200 as CreateSystemone200
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone400 as CreateSystemone400
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone401 as CreateSystemone401
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone402 as CreateSystemone402
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone403 as CreateSystemone403
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone404 as CreateSystemone404
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone413 as CreateSystemone413
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone429 as CreateSystemone429
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone500 as CreateSystemone500
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone502 as CreateSystemone502
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone503 as CreateSystemone503
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone524 as CreateSystemone524
from pyfect.ai.openrouter.generated._schemas_2 import CreateSystemone529 as CreateSystemone529
from pyfect.ai.openrouter.generated._schemas_2 import ListToolsParams as ListToolsParams
from pyfect.ai.openrouter.generated._schemas_2 import ListTools200 as ListTools200
from pyfect.ai.openrouter.generated._schemas_2 import ListTools401 as ListTools401
from pyfect.ai.openrouter.generated._schemas_2 import ListTools403 as ListTools403
from pyfect.ai.openrouter.generated._schemas_2 import ListTools404 as ListTools404
from pyfect.ai.openrouter.generated._schemas_2 import ListTools500 as ListTools500
from pyfect.ai.openrouter.generated._schemas_2 import GetToolParams as GetToolParams
from pyfect.ai.openrouter.generated._schemas_2 import GetTool200 as GetTool200
from pyfect.ai.openrouter.generated._schemas_2 import GetTool401 as GetTool401
from pyfect.ai.openrouter.generated._schemas_2 import GetTool403 as GetTool403
from pyfect.ai.openrouter.generated._schemas_2 import GetTool404 as GetTool404
from pyfect.ai.openrouter.generated._schemas_2 import GetTool500 as GetTool500
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnectionsParams as ListInternConnectionsParams
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections200 as ListInternConnections200
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections400 as ListInternConnections400
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections401 as ListInternConnections401
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections403 as ListInternConnections403
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections404 as ListInternConnections404
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections408 as ListInternConnections408
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections429 as ListInternConnections429
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections500 as ListInternConnections500
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections502 as ListInternConnections502
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections503 as ListInternConnections503
from pyfect.ai.openrouter.generated._schemas_2 import ListInternConnections504 as ListInternConnections504
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecretsParams as ListInternEffectiveVaultSecretsParams
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets200 as ListInternEffectiveVaultSecrets200
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets400 as ListInternEffectiveVaultSecrets400
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets401 as ListInternEffectiveVaultSecrets401
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets403 as ListInternEffectiveVaultSecrets403
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets404 as ListInternEffectiveVaultSecrets404
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets408 as ListInternEffectiveVaultSecrets408
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets429 as ListInternEffectiveVaultSecrets429
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets500 as ListInternEffectiveVaultSecrets500
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets502 as ListInternEffectiveVaultSecrets502
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets503 as ListInternEffectiveVaultSecrets503
from pyfect.ai.openrouter.generated._schemas_2 import ListInternEffectiveVaultSecrets504 as ListInternEffectiveVaultSecrets504
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecretsParams as ListInternVaultSecretsParams
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets200 as ListInternVaultSecrets200
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets400 as ListInternVaultSecrets400
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets401 as ListInternVaultSecrets401
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets403 as ListInternVaultSecrets403
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets404 as ListInternVaultSecrets404
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets408 as ListInternVaultSecrets408
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets429 as ListInternVaultSecrets429
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets500 as ListInternVaultSecrets500
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets502 as ListInternVaultSecrets502
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets503 as ListInternVaultSecrets503
from pyfect.ai.openrouter.generated._schemas_2 import ListInternVaultSecrets504 as ListInternVaultSecrets504
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecretParams as StoreInternVaultSecretParams
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecretRequestJson as StoreInternVaultSecretRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret200 as StoreInternVaultSecret200
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret400 as StoreInternVaultSecret400
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret401 as StoreInternVaultSecret401
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret403 as StoreInternVaultSecret403
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret404 as StoreInternVaultSecret404
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret408 as StoreInternVaultSecret408
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret409 as StoreInternVaultSecret409
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret413 as StoreInternVaultSecret413
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret429 as StoreInternVaultSecret429
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret500 as StoreInternVaultSecret500
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret502 as StoreInternVaultSecret502
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret503 as StoreInternVaultSecret503
from pyfect.ai.openrouter.generated._schemas_2 import StoreInternVaultSecret504 as StoreInternVaultSecret504
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecretParams as DeleteInternVaultSecretParams
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret400 as DeleteInternVaultSecret400
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret401 as DeleteInternVaultSecret401
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret403 as DeleteInternVaultSecret403
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret404 as DeleteInternVaultSecret404
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret408 as DeleteInternVaultSecret408
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret409 as DeleteInternVaultSecret409
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret429 as DeleteInternVaultSecret429
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret500 as DeleteInternVaultSecret500
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret502 as DeleteInternVaultSecret502
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret503 as DeleteInternVaultSecret503
from pyfect.ai.openrouter.generated._schemas_2 import DeleteInternVaultSecret504 as DeleteInternVaultSecret504
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToInternParams as CopyVaultSecretsToInternParams
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToInternRequestJson as CopyVaultSecretsToInternRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern200 as CopyVaultSecretsToIntern200
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern400 as CopyVaultSecretsToIntern400
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern401 as CopyVaultSecretsToIntern401
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern403 as CopyVaultSecretsToIntern403
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern404 as CopyVaultSecretsToIntern404
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern408 as CopyVaultSecretsToIntern408
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern409 as CopyVaultSecretsToIntern409
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern413 as CopyVaultSecretsToIntern413
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern429 as CopyVaultSecretsToIntern429
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern500 as CopyVaultSecretsToIntern500
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern502 as CopyVaultSecretsToIntern502
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern503 as CopyVaultSecretsToIntern503
from pyfect.ai.openrouter.generated._schemas_2 import CopyVaultSecretsToIntern504 as CopyVaultSecretsToIntern504
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecretsParams as ListVaultSecretsParams
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets200 as ListVaultSecrets200
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets400 as ListVaultSecrets400
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets401 as ListVaultSecrets401
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets403 as ListVaultSecrets403
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets404 as ListVaultSecrets404
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets408 as ListVaultSecrets408
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets429 as ListVaultSecrets429
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets500 as ListVaultSecrets500
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets502 as ListVaultSecrets502
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets503 as ListVaultSecrets503
from pyfect.ai.openrouter.generated._schemas_2 import ListVaultSecrets504 as ListVaultSecrets504
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecretParams as StoreVaultSecretParams
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecretRequestJson as StoreVaultSecretRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret200 as StoreVaultSecret200
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret400 as StoreVaultSecret400
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret401 as StoreVaultSecret401
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret403 as StoreVaultSecret403
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret404 as StoreVaultSecret404
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret408 as StoreVaultSecret408
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret409 as StoreVaultSecret409
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret413 as StoreVaultSecret413
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret429 as StoreVaultSecret429
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret500 as StoreVaultSecret500
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret502 as StoreVaultSecret502
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret503 as StoreVaultSecret503
from pyfect.ai.openrouter.generated._schemas_2 import StoreVaultSecret504 as StoreVaultSecret504
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecretParams as DeleteVaultSecretParams
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret400 as DeleteVaultSecret400
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret401 as DeleteVaultSecret401
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret403 as DeleteVaultSecret403
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret404 as DeleteVaultSecret404
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret408 as DeleteVaultSecret408
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret409 as DeleteVaultSecret409
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret429 as DeleteVaultSecret429
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret500 as DeleteVaultSecret500
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret502 as DeleteVaultSecret502
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret503 as DeleteVaultSecret503
from pyfect.ai.openrouter.generated._schemas_2 import DeleteVaultSecret504 as DeleteVaultSecret504
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideosParams as CreateVideosParams
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideosRequestJson as CreateVideosRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos202 as CreateVideos202
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos400 as CreateVideos400
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos401 as CreateVideos401
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos402 as CreateVideos402
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos403 as CreateVideos403
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos404 as CreateVideos404
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos413 as CreateVideos413
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos429 as CreateVideos429
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos499 as CreateVideos499
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos500 as CreateVideos500
from pyfect.ai.openrouter.generated._schemas_2 import CreateVideos503 as CreateVideos503
from pyfect.ai.openrouter.generated._schemas_2 import GetVideosParams as GetVideosParams
from pyfect.ai.openrouter.generated._schemas_2 import GetVideos200 as GetVideos200
from pyfect.ai.openrouter.generated._schemas_2 import GetVideos401 as GetVideos401
from pyfect.ai.openrouter.generated._schemas_2 import GetVideos403 as GetVideos403
from pyfect.ai.openrouter.generated._schemas_2 import GetVideos404 as GetVideos404
from pyfect.ai.openrouter.generated._schemas_2 import GetVideos500 as GetVideos500
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosContentParams as ListVideosContentParams
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosContent400 as ListVideosContent400
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosContent401 as ListVideosContent401
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosContent403 as ListVideosContent403
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosContent404 as ListVideosContent404
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosContent409 as ListVideosContent409
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosContent410 as ListVideosContent410
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosContent500 as ListVideosContent500
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosContent502 as ListVideosContent502
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosModelsParams as ListVideosModelsParams
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosModels200 as ListVideosModels200
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosModels400 as ListVideosModels400
from pyfect.ai.openrouter.generated._schemas_2 import ListVideosModels500 as ListVideosModels500
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspacesParams as ListWorkspacesParams
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaces200 as ListWorkspaces200
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaces401 as ListWorkspaces401
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaces403 as ListWorkspaces403
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaces500 as ListWorkspaces500
from pyfect.ai.openrouter.generated._schemas_2 import CreateWorkspaceParams as CreateWorkspaceParams
from pyfect.ai.openrouter.generated._schemas_2 import CreateWorkspaceRequestJson as CreateWorkspaceRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import CreateWorkspace201 as CreateWorkspace201
from pyfect.ai.openrouter.generated._schemas_2 import CreateWorkspace400 as CreateWorkspace400
from pyfect.ai.openrouter.generated._schemas_2 import CreateWorkspace401 as CreateWorkspace401
from pyfect.ai.openrouter.generated._schemas_2 import CreateWorkspace403 as CreateWorkspace403
from pyfect.ai.openrouter.generated._schemas_2 import CreateWorkspace500 as CreateWorkspace500
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspaceParams as GetWorkspaceParams
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspace200 as GetWorkspace200
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspace401 as GetWorkspace401
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspace403 as GetWorkspace403
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspace404 as GetWorkspace404
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspace500 as GetWorkspace500
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspaceParams as DeleteWorkspaceParams
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspace200 as DeleteWorkspace200
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspace400 as DeleteWorkspace400
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspace401 as DeleteWorkspace401
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspace403 as DeleteWorkspace403
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspace404 as DeleteWorkspace404
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspace500 as DeleteWorkspace500
from pyfect.ai.openrouter.generated._schemas_2 import UpdateWorkspaceParams as UpdateWorkspaceParams
from pyfect.ai.openrouter.generated._schemas_2 import UpdateWorkspaceRequestJson as UpdateWorkspaceRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import UpdateWorkspace200 as UpdateWorkspace200
from pyfect.ai.openrouter.generated._schemas_2 import UpdateWorkspace400 as UpdateWorkspace400
from pyfect.ai.openrouter.generated._schemas_2 import UpdateWorkspace401 as UpdateWorkspace401
from pyfect.ai.openrouter.generated._schemas_2 import UpdateWorkspace403 as UpdateWorkspace403
from pyfect.ai.openrouter.generated._schemas_2 import UpdateWorkspace404 as UpdateWorkspace404
from pyfect.ai.openrouter.generated._schemas_2 import UpdateWorkspace500 as UpdateWorkspace500
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceMembersParams as ListWorkspaceMembersParams
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceMembers200 as ListWorkspaceMembers200
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceMembers401 as ListWorkspaceMembers401
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceMembers403 as ListWorkspaceMembers403
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceMembers404 as ListWorkspaceMembers404
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceMembers500 as ListWorkspaceMembers500
from pyfect.ai.openrouter.generated._schemas_2 import BulkAddWorkspaceMembersParams as BulkAddWorkspaceMembersParams
from pyfect.ai.openrouter.generated._schemas_2 import BulkAddWorkspaceMembersRequestJson as BulkAddWorkspaceMembersRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import BulkAddWorkspaceMembers200 as BulkAddWorkspaceMembers200
from pyfect.ai.openrouter.generated._schemas_2 import BulkAddWorkspaceMembers400 as BulkAddWorkspaceMembers400
from pyfect.ai.openrouter.generated._schemas_2 import BulkAddWorkspaceMembers401 as BulkAddWorkspaceMembers401
from pyfect.ai.openrouter.generated._schemas_2 import BulkAddWorkspaceMembers403 as BulkAddWorkspaceMembers403
from pyfect.ai.openrouter.generated._schemas_2 import BulkAddWorkspaceMembers404 as BulkAddWorkspaceMembers404
from pyfect.ai.openrouter.generated._schemas_2 import BulkAddWorkspaceMembers500 as BulkAddWorkspaceMembers500
from pyfect.ai.openrouter.generated._schemas_2 import BulkRemoveWorkspaceMembersParams as BulkRemoveWorkspaceMembersParams
from pyfect.ai.openrouter.generated._schemas_2 import BulkRemoveWorkspaceMembersRequestJson as BulkRemoveWorkspaceMembersRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import BulkRemoveWorkspaceMembers200 as BulkRemoveWorkspaceMembers200
from pyfect.ai.openrouter.generated._schemas_2 import BulkRemoveWorkspaceMembers400 as BulkRemoveWorkspaceMembers400
from pyfect.ai.openrouter.generated._schemas_2 import BulkRemoveWorkspaceMembers401 as BulkRemoveWorkspaceMembers401
from pyfect.ai.openrouter.generated._schemas_2 import BulkRemoveWorkspaceMembers403 as BulkRemoveWorkspaceMembers403
from pyfect.ai.openrouter.generated._schemas_2 import BulkRemoveWorkspaceMembers404 as BulkRemoveWorkspaceMembers404
from pyfect.ai.openrouter.generated._schemas_2 import BulkRemoveWorkspaceMembers500 as BulkRemoveWorkspaceMembers500
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceBudgetsParams as ListWorkspaceBudgetsParams
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceBudgets200 as ListWorkspaceBudgets200
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceBudgets401 as ListWorkspaceBudgets401
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceBudgets403 as ListWorkspaceBudgets403
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceBudgets404 as ListWorkspaceBudgets404
from pyfect.ai.openrouter.generated._schemas_2 import ListWorkspaceBudgets500 as ListWorkspaceBudgets500
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspaceBudgetParams as GetWorkspaceBudgetParams
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspaceBudget200 as GetWorkspaceBudget200
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspaceBudget400 as GetWorkspaceBudget400
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspaceBudget401 as GetWorkspaceBudget401
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspaceBudget403 as GetWorkspaceBudget403
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspaceBudget404 as GetWorkspaceBudget404
from pyfect.ai.openrouter.generated._schemas_2 import GetWorkspaceBudget500 as GetWorkspaceBudget500
from pyfect.ai.openrouter.generated._schemas_2 import UpsertWorkspaceBudgetParams as UpsertWorkspaceBudgetParams
from pyfect.ai.openrouter.generated._schemas_2 import UpsertWorkspaceBudgetRequestJson as UpsertWorkspaceBudgetRequestJson
from pyfect.ai.openrouter.generated._schemas_2 import UpsertWorkspaceBudget200 as UpsertWorkspaceBudget200
from pyfect.ai.openrouter.generated._schemas_2 import UpsertWorkspaceBudget400 as UpsertWorkspaceBudget400
from pyfect.ai.openrouter.generated._schemas_2 import UpsertWorkspaceBudget401 as UpsertWorkspaceBudget401
from pyfect.ai.openrouter.generated._schemas_2 import UpsertWorkspaceBudget403 as UpsertWorkspaceBudget403
from pyfect.ai.openrouter.generated._schemas_2 import UpsertWorkspaceBudget404 as UpsertWorkspaceBudget404
from pyfect.ai.openrouter.generated._schemas_2 import UpsertWorkspaceBudget500 as UpsertWorkspaceBudget500
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspaceBudgetParams as DeleteWorkspaceBudgetParams
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspaceBudget200 as DeleteWorkspaceBudget200
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspaceBudget400 as DeleteWorkspaceBudget400
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspaceBudget401 as DeleteWorkspaceBudget401
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspaceBudget403 as DeleteWorkspaceBudget403
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspaceBudget404 as DeleteWorkspaceBudget404
from pyfect.ai.openrouter.generated._schemas_2 import DeleteWorkspaceBudget500 as DeleteWorkspaceBudget500

__all__ = [
    "AABenchmarkEntry",
    "AccountGuardrailPolicy",
    "AccountGuardrailPolicyRequest",
    "AccountGuardrailPolicyResponse",
    "ActivatePrivateEndpoint200",
    "ActivatePrivateEndpoint400",
    "ActivatePrivateEndpoint401",
    "ActivatePrivateEndpoint403",
    "ActivatePrivateEndpoint404",
    "ActivatePrivateEndpoint408",
    "ActivatePrivateEndpoint409",
    "ActivatePrivateEndpoint422",
    "ActivatePrivateEndpoint500",
    "ActivatePrivateEndpoint502",
    "ActivatePrivateEndpointParams",
    "ActivityItem",
    "ActivityResponse",
    "AdditionalToolsItem",
    "AdvisorReasoning",
    "AdvisorServerToolConfig",
    "AdvisorServerTool_OpenRouter",
    "AgentMessageItem",
    "Alignment",
    "AlignmentAllowedCallRecord",
    "AlignmentBlockedCallRecord",
    "AlignmentCallRecord",
    "AlignmentChatAudio",
    "AlignmentChatImage",
    "AlignmentChatRejected",
    "AlignmentChatToolCall",
    "AlignmentPlugin",
    "AlignmentRejected",
    "AlignmentResponsesRejected",
    "AlignmentRule",
    "AlignmentRuleRecord",
    "AlignmentUnavailableCallRecord",
    "AnnotationAddedEvent",
    "AnthropicAdvisorMessageUsageIteration",
    "AnthropicAdvisorToolResult",
    "AnthropicAllowedCallers",
    "AnthropicBase64ImageSource",
    "AnthropicBase64PdfSource",
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
    "AnthropicContainerSkill",
    "AnthropicContainerUpload",
    "AnthropicDirectCaller",
    "AnthropicDocumentBlock",
    "AnthropicDocumentBlockParam",
    "AnthropicEncryptedCodeExecutionResult",
    "AnthropicFile",
    "AnthropicFileDeleted",
    "AnthropicFileDocumentSource",
    "AnthropicFileList",
    "AnthropicImageBlockParam",
    "AnthropicImageMimeType",
    "AnthropicInputTokensClearAtLeast",
    "AnthropicInputTokensTrigger",
    "AnthropicInputTransformation",
    "AnthropicIterationCacheCreation",
    "AnthropicMessageOutputConfig",
    "AnthropicMessageUsageIteration",
    "AnthropicMessagesErrorResponse",
    "AnthropicOutputEffort",
    "AnthropicOutputTokensDetails",
    "AnthropicPlainTextSource",
    "AnthropicRedactedThinkingBlock",
    "AnthropicRefusalStopDetails",
    "AnthropicSafeguard",
    "AnthropicSafeguardResult",
    "AnthropicSearchResultBlockParam",
    "AnthropicServerToolErrorCode",
    "AnthropicServerToolUsage",
    "AnthropicServiceTier",
    "AnthropicSpeed",
    "AnthropicSystemClearAt",
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
    "AnthropicThinkingBlockBinding",
    "AnthropicThinkingDisplay",
    "AnthropicThinkingTurns",
    "AnthropicToolReference",
    "AnthropicToolSearchContent",
    "AnthropicToolSearchResult",
    "AnthropicToolSearchResultError",
    "AnthropicToolSearchToolBm25",
    "AnthropicToolSearchToolRegex",
    "AnthropicToolSearchToolResult",
    "AnthropicToolUnion",
    "AnthropicToolUseBlock",
    "AnthropicToolUsesKeep",
    "AnthropicToolUsesTrigger",
    "AnthropicUnknownUsageIteration",
    "AnthropicUrlImageSource",
    "AnthropicUrlPdfSource",
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
    "ArmorAutoMode",
    "ArmorContext",
    "ArmorEnvironmentEntry",
    "ArmorPlugin",
    "ArmorRule",
    "ArmorSafeguardResult",
    "AutoBetaRouterPlugin",
    "AutoRouterPlugin",
    "BYOKKey",
    "BYOKProviderSlug",
    "BadGatewayResponse",
    "BadGatewayResponseErrorData",
    "BadRequestResponse",
    "BadRequestResponseErrorData",
    "BaseInputs",
    "BaseReasoningConfig",
    "BashServerTool",
    "BashServerToolConfig",
    "BashServerToolEngine",
    "BashServerToolEnvironment",
    "BatchDeletedObject",
    "BatchDeletionOutcome",
    "BatchDeletionTargets",
    "BatchErrorResponse",
    "BatchListItem",
    "BatchListResponse",
    "BatchListStatus",
    "BatchListTimestamp",
    "BatchObject",
    "BatchPaymentRequiredResponse",
    "BatchProviderPreferences",
    "BatchSubmitBody",
    "BooleanCapability",
    "BudgetAccountGuardrailPolicy",
    "BudgetAccountGuardrailPolicyRequest",
    "BudgetGuardrailPolicy",
    "BudgetGuardrailPolicyDetail",
    "BudgetGuardrailPolicyDetailResponse",
    "BudgetGuardrailPolicyResponse",
    "BudgetGuardrailPolicySummary",
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
    "BulkAssignKeysToGuardrail403",
    "BulkAssignKeysToGuardrail404",
    "BulkAssignKeysToGuardrail500",
    "BulkAssignKeysToGuardrailParams",
    "BulkAssignKeysToGuardrailRequestJson",
    "BulkAssignMembersRequest",
    "BulkAssignMembersResponse",
    "BulkAssignMembersToGuardrail200",
    "BulkAssignMembersToGuardrail400",
    "BulkAssignMembersToGuardrail401",
    "BulkAssignMembersToGuardrail403",
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
    "BulkUnassignKeysFromGuardrail403",
    "BulkUnassignKeysFromGuardrail404",
    "BulkUnassignKeysFromGuardrail500",
    "BulkUnassignKeysFromGuardrailParams",
    "BulkUnassignKeysFromGuardrailRequestJson",
    "BulkUnassignKeysRequest",
    "BulkUnassignKeysResponse",
    "BulkUnassignMembersFromGuardrail200",
    "BulkUnassignMembersFromGuardrail400",
    "BulkUnassignMembersFromGuardrail401",
    "BulkUnassignMembersFromGuardrail403",
    "BulkUnassignMembersFromGuardrail404",
    "BulkUnassignMembersFromGuardrail500",
    "BulkUnassignMembersFromGuardrailParams",
    "BulkUnassignMembersFromGuardrailRequestJson",
    "BulkUnassignMembersRequest",
    "BulkUnassignMembersResponse",
    "CapabilityDescriptor",
    "ChangeApiKeyPolicyAssignment200",
    "ChangeApiKeyPolicyAssignment400",
    "ChangeApiKeyPolicyAssignment401",
    "ChangeApiKeyPolicyAssignment403",
    "ChangeApiKeyPolicyAssignment404",
    "ChangeApiKeyPolicyAssignment409",
    "ChangeApiKeyPolicyAssignment500",
    "ChangeApiKeyPolicyAssignmentParams",
    "ChangeApiKeyPolicyAssignmentRequestJson",
    "ChangeGuardrailPolicyAssignmentRequest",
    "ChangeGuardrailPolicyAssignmentResponse",
    "ChangeMemberPolicyAssignment200",
    "ChangeMemberPolicyAssignment400",
    "ChangeMemberPolicyAssignment401",
    "ChangeMemberPolicyAssignment403",
    "ChangeMemberPolicyAssignment404",
    "ChangeMemberPolicyAssignment409",
    "ChangeMemberPolicyAssignment500",
    "ChangeMemberPolicyAssignmentParams",
    "ChangeMemberPolicyAssignmentRequestJson",
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
    "ChatDynamicServerTool",
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
    "ClassifierFiltersFilter",
    "ClassifierScalarFilter",
    "ClassifierScalarFilterOperator",
    "ClassifierSetFilter",
    "ClassifierSetFilterOperator",
    "ClientClosedRequestResponse",
    "ClientClosedRequestResponseErrorData",
    "CodeInterpreterCallCodeDeltaEvent",
    "CodeInterpreterCallCodeDoneEvent",
    "CodeInterpreterCallCompletedEvent",
    "CodeInterpreterCallInProgressEvent",
    "CodeInterpreterCallInterpretingEvent",
    "CodeInterpreterFileOutput",
    "CodeInterpreterImageOutput",
    "CodeInterpreterLogsOutput",
    "CodeInterpreterServerTool",
    "CodexLocalShellTool",
    "CompactionItem",
    "CompactionTriggerItem",
    "CompoundFilter",
    "ComputerUseServerTool",
    "ConfigurationUpdate",
    "ConfigurationUpdateItem",
    "ConfigurationUpdateReasoning",
    "ConflictResponse",
    "ConflictResponseErrorData",
    "ContainerAutoEnvironment",
    "ContainerFile",
    "ContainerFileIds",
    "ContainerFileListResponse",
    "ContainerNetworkPolicy",
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
    "CopyVaultSecretsToIntern200",
    "CopyVaultSecretsToIntern400",
    "CopyVaultSecretsToIntern401",
    "CopyVaultSecretsToIntern403",
    "CopyVaultSecretsToIntern404",
    "CopyVaultSecretsToIntern408",
    "CopyVaultSecretsToIntern409",
    "CopyVaultSecretsToIntern413",
    "CopyVaultSecretsToIntern429",
    "CopyVaultSecretsToIntern500",
    "CopyVaultSecretsToIntern502",
    "CopyVaultSecretsToIntern503",
    "CopyVaultSecretsToIntern504",
    "CopyVaultSecretsToInternParams",
    "CopyVaultSecretsToInternRequestJson",
    "CostDetails",
    "CreateAccountPolicy201",
    "CreateAccountPolicy400",
    "CreateAccountPolicy401",
    "CreateAccountPolicy403",
    "CreateAccountPolicy404",
    "CreateAccountPolicy409",
    "CreateAccountPolicy500",
    "CreateAccountPolicyParams",
    "CreateAccountPolicyRequestJson",
    "CreateApiAlphaDecisions200",
    "CreateApiAlphaDecisions400",
    "CreateApiAlphaDecisions401",
    "CreateApiAlphaDecisions402",
    "CreateApiAlphaDecisions403",
    "CreateApiAlphaDecisions404",
    "CreateApiAlphaDecisions413",
    "CreateApiAlphaDecisions429",
    "CreateApiAlphaDecisions500",
    "CreateApiAlphaDecisions502",
    "CreateApiAlphaDecisions503",
    "CreateApiAlphaDecisions524",
    "CreateApiAlphaDecisions529",
    "CreateApiAlphaDecisionsParams",
    "CreateApiAlphaDecisionsRequestJson",
    "CreateApiAlphaExtractions200",
    "CreateApiAlphaExtractions400",
    "CreateApiAlphaExtractions401",
    "CreateApiAlphaExtractions402",
    "CreateApiAlphaExtractions403",
    "CreateApiAlphaExtractions404",
    "CreateApiAlphaExtractions413",
    "CreateApiAlphaExtractions429",
    "CreateApiAlphaExtractions500",
    "CreateApiAlphaExtractions502",
    "CreateApiAlphaExtractions503",
    "CreateApiAlphaExtractions524",
    "CreateApiAlphaExtractions529",
    "CreateApiAlphaExtractionsParams",
    "CreateApiAlphaExtractionsRequestJson",
    "CreateAudioSpeech400",
    "CreateAudioSpeech401",
    "CreateAudioSpeech402",
    "CreateAudioSpeech403",
    "CreateAudioSpeech404",
    "CreateAudioSpeech413",
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
    "CreateAudioTranscriptions403",
    "CreateAudioTranscriptions404",
    "CreateAudioTranscriptions413",
    "CreateAudioTranscriptions429",
    "CreateAudioTranscriptions500",
    "CreateAudioTranscriptions502",
    "CreateAudioTranscriptions503",
    "CreateAudioTranscriptions504",
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
    "CreateAuthKeysCode503",
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
    "CreateBatches202",
    "CreateBatches400",
    "CreateBatches401",
    "CreateBatches402",
    "CreateBatches403",
    "CreateBatches404",
    "CreateBatches413",
    "CreateBatches422",
    "CreateBatches429",
    "CreateBatches500",
    "CreateBatches502",
    "CreateBatchesParams",
    "CreateBatchesRequestJson",
    "CreateBudgetGuardrailPolicyRequest",
    "CreateBudgetPolicy201",
    "CreateBudgetPolicy400",
    "CreateBudgetPolicy401",
    "CreateBudgetPolicy403",
    "CreateBudgetPolicy404",
    "CreateBudgetPolicy409",
    "CreateBudgetPolicy500",
    "CreateBudgetPolicyParams",
    "CreateBudgetPolicyRequestJson",
    "CreateCoinbaseCharge410",
    "CreateCoinbaseChargeParams",
    "CreateCreditPurchaseRequest",
    "CreateCreditsPurchases202",
    "CreateCreditsPurchases400",
    "CreateCreditsPurchases401",
    "CreateCreditsPurchases402",
    "CreateCreditsPurchases403",
    "CreateCreditsPurchases404",
    "CreateCreditsPurchases409",
    "CreateCreditsPurchases429",
    "CreateCreditsPurchases500",
    "CreateCreditsPurchases503",
    "CreateCreditsPurchasesParams",
    "CreateCreditsPurchasesRequestJson",
    "CreateEmbeddings200",
    "CreateEmbeddings200Sse",
    "CreateEmbeddings400",
    "CreateEmbeddings401",
    "CreateEmbeddings402",
    "CreateEmbeddings403",
    "CreateEmbeddings404",
    "CreateEmbeddings408",
    "CreateEmbeddings413",
    "CreateEmbeddings429",
    "CreateEmbeddings499",
    "CreateEmbeddings500",
    "CreateEmbeddings502",
    "CreateEmbeddings503",
    "CreateEmbeddings504",
    "CreateEmbeddings524",
    "CreateEmbeddings529",
    "CreateEmbeddingsParams",
    "CreateEmbeddingsRequestJson",
    "CreateExternalUser201",
    "CreateExternalUser400",
    "CreateExternalUser401",
    "CreateExternalUser404",
    "CreateExternalUser409",
    "CreateExternalUser500",
    "CreateExternalUserParams",
    "CreateExternalUserRequest",
    "CreateExternalUserRequestJson",
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
    "CreateModelAvailabilityGuardrailPolicyRequest",
    "CreateModelAvailabilityPolicy201",
    "CreateModelAvailabilityPolicy400",
    "CreateModelAvailabilityPolicy401",
    "CreateModelAvailabilityPolicy403",
    "CreateModelAvailabilityPolicy404",
    "CreateModelAvailabilityPolicy409",
    "CreateModelAvailabilityPolicy500",
    "CreateModelAvailabilityPolicyParams",
    "CreateModelAvailabilityPolicyRequestJson",
    "CreateModerationGuardrailPolicyRequest",
    "CreateModerationPolicy201",
    "CreateModerationPolicy400",
    "CreateModerationPolicy401",
    "CreateModerationPolicy403",
    "CreateModerationPolicy404",
    "CreateModerationPolicy409",
    "CreateModerationPolicy500",
    "CreateModerationPolicyParams",
    "CreateModerationPolicyRequestJson",
    "CreateOauthToken200",
    "CreateOauthToken400",
    "CreateOauthToken429",
    "CreateOauthToken500",
    "CreateOauthToken503",
    "CreateOauthTokenParams",
    "CreateOauthTokenRequestFormUrlEncoded",
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
    "CreatePrivateEndpoint201",
    "CreatePrivateEndpoint400",
    "CreatePrivateEndpoint401",
    "CreatePrivateEndpoint403",
    "CreatePrivateEndpoint404",
    "CreatePrivateEndpoint408",
    "CreatePrivateEndpoint409",
    "CreatePrivateEndpoint422",
    "CreatePrivateEndpoint500",
    "CreatePrivateEndpoint502",
    "CreatePrivateEndpointParams",
    "CreatePrivateEndpointRequest",
    "CreatePrivateEndpointRequestJson",
    "CreatePrivateEndpointValidationFailedResponse",
    "CreatePrivateProvider201",
    "CreatePrivateProvider400",
    "CreatePrivateProvider401",
    "CreatePrivateProvider403",
    "CreatePrivateProvider404",
    "CreatePrivateProvider408",
    "CreatePrivateProvider409",
    "CreatePrivateProvider422",
    "CreatePrivateProvider429",
    "CreatePrivateProvider500",
    "CreatePrivateProvider502",
    "CreatePrivateProviderParams",
    "CreatePrivateProviderRequest",
    "CreatePrivateProviderRequestJson",
    "CreateRerank200",
    "CreateRerank200Sse",
    "CreateRerank400",
    "CreateRerank401",
    "CreateRerank402",
    "CreateRerank403",
    "CreateRerank404",
    "CreateRerank413",
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
    "CreateScimGroupMapping201",
    "CreateScimGroupMapping400",
    "CreateScimGroupMapping401",
    "CreateScimGroupMapping403",
    "CreateScimGroupMapping404",
    "CreateScimGroupMapping409",
    "CreateScimGroupMapping500",
    "CreateScimGroupMappingParams",
    "CreateScimGroupMappingRequest",
    "CreateScimGroupMappingRequestJson",
    "CreateScimGroupMappingResponse",
    "CreateScimSyncJob202",
    "CreateScimSyncJob401",
    "CreateScimSyncJob403",
    "CreateScimSyncJob404",
    "CreateScimSyncJob500",
    "CreateScimSyncJobParams",
    "CreateScimSyncJobResponse",
    "CreateSystemone200",
    "CreateSystemone400",
    "CreateSystemone401",
    "CreateSystemone402",
    "CreateSystemone403",
    "CreateSystemone404",
    "CreateSystemone413",
    "CreateSystemone429",
    "CreateSystemone500",
    "CreateSystemone502",
    "CreateSystemone503",
    "CreateSystemone524",
    "CreateSystemone529",
    "CreateSystemoneParams",
    "CreateSystemoneRequestJson",
    "CreateVideos202",
    "CreateVideos400",
    "CreateVideos401",
    "CreateVideos402",
    "CreateVideos403",
    "CreateVideos404",
    "CreateVideos413",
    "CreateVideos429",
    "CreateVideos499",
    "CreateVideos500",
    "CreateVideos503",
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
    "CreditPurchase",
    "CreditPurchaseResponse",
    "CustomTool",
    "CustomToolCallInputDeltaEvent",
    "CustomToolCallInputDoneEvent",
    "CustomToolCallItem",
    "CustomToolCallOutputItem",
    "DABenchmarkEntry",
    "DatetimeServerTool",
    "DatetimeServerToolConfig",
    "DebugEvent",
    "Decisions",
    "DecisionsBoxAnswer",
    "DecisionsBoxQuestion",
    "DecisionsChoiceAnswer",
    "DecisionsChoiceQuestion",
    "DecisionsImageAsset",
    "DecisionsNoulAnswer",
    "DecisionsNoulQuestion",
    "DecisionsRefusalAnswer",
    "DecisionsRequest",
    "DecisionsResponse",
    "DecisionsScoreAnswer",
    "DecisionsScoreQuestion",
    "DecisionsUrlCitationAnnotation",
    "DecisionsUsageInputTokensDetails",
    "DefaultParameters",
    "DeferredBm25Search",
    "DeferredCustomSearch",
    "DeferredRegexSearch",
    "DeferredToolsControl",
    "DeferredToolsDetails",
    "DeferredToolsSearchStrategy",
    "DeleteAccountPolicy200",
    "DeleteAccountPolicy400",
    "DeleteAccountPolicy401",
    "DeleteAccountPolicy403",
    "DeleteAccountPolicy404",
    "DeleteAccountPolicy409",
    "DeleteAccountPolicy500",
    "DeleteAccountPolicyParams",
    "DeleteBYOKKey200",
    "DeleteBYOKKey401",
    "DeleteBYOKKey403",
    "DeleteBYOKKey404",
    "DeleteBYOKKey500",
    "DeleteBYOKKeyParams",
    "DeleteBYOKKeyResponse",
    "DeleteBatch200",
    "DeleteBatch401",
    "DeleteBatch404",
    "DeleteBatch409",
    "DeleteBatch429",
    "DeleteBatch500",
    "DeleteBatch502",
    "DeleteBatchParams",
    "DeleteBudgetPolicy200",
    "DeleteBudgetPolicy400",
    "DeleteBudgetPolicy401",
    "DeleteBudgetPolicy403",
    "DeleteBudgetPolicy404",
    "DeleteBudgetPolicy409",
    "DeleteBudgetPolicy500",
    "DeleteBudgetPolicyParams",
    "DeleteExternalUser400",
    "DeleteExternalUser401",
    "DeleteExternalUser404",
    "DeleteExternalUser500",
    "DeleteExternalUserParams",
    "DeleteFile200",
    "DeleteFile401",
    "DeleteFile403",
    "DeleteFile404",
    "DeleteFile429",
    "DeleteFile500",
    "DeleteFile502",
    "DeleteFile503",
    "DeleteFileParams",
    "DeleteGuardrail200",
    "DeleteGuardrail401",
    "DeleteGuardrail403",
    "DeleteGuardrail404",
    "DeleteGuardrail500",
    "DeleteGuardrailParams",
    "DeleteGuardrailPolicyResponse",
    "DeleteGuardrailResponse",
    "DeleteInternVaultSecret400",
    "DeleteInternVaultSecret401",
    "DeleteInternVaultSecret403",
    "DeleteInternVaultSecret404",
    "DeleteInternVaultSecret408",
    "DeleteInternVaultSecret409",
    "DeleteInternVaultSecret429",
    "DeleteInternVaultSecret500",
    "DeleteInternVaultSecret502",
    "DeleteInternVaultSecret503",
    "DeleteInternVaultSecret504",
    "DeleteInternVaultSecretParams",
    "DeleteKeys200",
    "DeleteKeys401",
    "DeleteKeys403",
    "DeleteKeys404",
    "DeleteKeys429",
    "DeleteKeys500",
    "DeleteKeysParams",
    "DeleteModelAvailabilityPolicy200",
    "DeleteModelAvailabilityPolicy400",
    "DeleteModelAvailabilityPolicy401",
    "DeleteModelAvailabilityPolicy403",
    "DeleteModelAvailabilityPolicy404",
    "DeleteModelAvailabilityPolicy409",
    "DeleteModelAvailabilityPolicy500",
    "DeleteModelAvailabilityPolicyParams",
    "DeleteModerationPolicy200",
    "DeleteModerationPolicy400",
    "DeleteModerationPolicy401",
    "DeleteModerationPolicy403",
    "DeleteModerationPolicy404",
    "DeleteModerationPolicy409",
    "DeleteModerationPolicy500",
    "DeleteModerationPolicyParams",
    "DeleteObservabilityDestination200",
    "DeleteObservabilityDestination401",
    "DeleteObservabilityDestination403",
    "DeleteObservabilityDestination404",
    "DeleteObservabilityDestination500",
    "DeleteObservabilityDestinationParams",
    "DeleteObservabilityDestinationResponse",
    "DeletePreset200",
    "DeletePreset400",
    "DeletePreset401",
    "DeletePreset403",
    "DeletePreset404",
    "DeletePreset409",
    "DeletePreset500",
    "DeletePresetParams",
    "DeletePrivateEndpoint200",
    "DeletePrivateEndpoint400",
    "DeletePrivateEndpoint401",
    "DeletePrivateEndpoint403",
    "DeletePrivateEndpoint404",
    "DeletePrivateEndpoint408",
    "DeletePrivateEndpoint409",
    "DeletePrivateEndpoint422",
    "DeletePrivateEndpoint500",
    "DeletePrivateEndpoint502",
    "DeletePrivateEndpointParams",
    "DeletePrivateEndpointResponse",
    "DeletePrivateProvider200",
    "DeletePrivateProvider400",
    "DeletePrivateProvider401",
    "DeletePrivateProvider403",
    "DeletePrivateProvider404",
    "DeletePrivateProvider408",
    "DeletePrivateProvider409",
    "DeletePrivateProvider422",
    "DeletePrivateProvider429",
    "DeletePrivateProvider500",
    "DeletePrivateProvider502",
    "DeletePrivateProviderParams",
    "DeleteScimGroupMapping200",
    "DeleteScimGroupMapping400",
    "DeleteScimGroupMapping401",
    "DeleteScimGroupMapping403",
    "DeleteScimGroupMapping404",
    "DeleteScimGroupMapping500",
    "DeleteScimGroupMappingParams",
    "DeleteScimGroupMappingResponse",
    "DeleteVaultSecret400",
    "DeleteVaultSecret401",
    "DeleteVaultSecret403",
    "DeleteVaultSecret404",
    "DeleteVaultSecret408",
    "DeleteVaultSecret409",
    "DeleteVaultSecret429",
    "DeleteVaultSecret500",
    "DeleteVaultSecret502",
    "DeleteVaultSecret503",
    "DeleteVaultSecret504",
    "DeleteVaultSecretParams",
    "DeleteWorkspace200",
    "DeleteWorkspace400",
    "DeleteWorkspace401",
    "DeleteWorkspace403",
    "DeleteWorkspace404",
    "DeleteWorkspace500",
    "DeleteWorkspaceBudget200",
    "DeleteWorkspaceBudget400",
    "DeleteWorkspaceBudget401",
    "DeleteWorkspaceBudget403",
    "DeleteWorkspaceBudget404",
    "DeleteWorkspaceBudget500",
    "DeleteWorkspaceBudgetParams",
    "DeleteWorkspaceBudgetResponse",
    "DeleteWorkspaceParams",
    "DeleteWorkspaceResponse",
    "DeprecatedRoute",
    "DisablePrivateEndpoint200",
    "DisablePrivateEndpoint400",
    "DisablePrivateEndpoint401",
    "DisablePrivateEndpoint403",
    "DisablePrivateEndpoint404",
    "DisablePrivateEndpoint408",
    "DisablePrivateEndpoint409",
    "DisablePrivateEndpoint422",
    "DisablePrivateEndpoint500",
    "DisablePrivateEndpoint502",
    "DisablePrivateEndpointParams",
    "DownloadContainerFileContent400",
    "DownloadContainerFileContent401",
    "DownloadContainerFileContent403",
    "DownloadContainerFileContent404",
    "DownloadContainerFileContent429",
    "DownloadContainerFileContent500",
    "DownloadContainerFileContent503",
    "DownloadContainerFileContentParams",
    "DownloadFileContent400",
    "DownloadFileContent401",
    "DownloadFileContent403",
    "DownloadFileContent404",
    "DownloadFileContent429",
    "DownloadFileContent500",
    "DownloadFileContent502",
    "DownloadFileContent503",
    "DownloadFileContentParams",
    "EasyInputMessage",
    "EdgeNetworkTimeoutResponse",
    "EdgeNetworkTimeoutResponseErrorData",
    "Embeddings",
    "EnablePrivateEndpoint200",
    "EnablePrivateEndpoint400",
    "EnablePrivateEndpoint401",
    "EnablePrivateEndpoint403",
    "EnablePrivateEndpoint404",
    "EnablePrivateEndpoint408",
    "EnablePrivateEndpoint409",
    "EnablePrivateEndpoint422",
    "EnablePrivateEndpoint500",
    "EnablePrivateEndpoint502",
    "EnablePrivateEndpointParams",
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
    "ExternalUser",
    "ExternalUserResponse",
    "ExtractionAsset",
    "ExtractionDateAnswer",
    "ExtractionDateField",
    "ExtractionDatetimeAnswer",
    "ExtractionDatetimeField",
    "ExtractionDurationAnswer",
    "ExtractionDurationField",
    "ExtractionEstimateAnswer",
    "ExtractionEstimateField",
    "ExtractionForecastAnswer",
    "ExtractionForecastField",
    "ExtractionForecastStep",
    "ExtractionListAnswer",
    "ExtractionListField",
    "ExtractionNumberAnswer",
    "ExtractionNumberField",
    "ExtractionTextAnswer",
    "ExtractionTextField",
    "ExtractionTimeAnswer",
    "ExtractionTimeField",
    "Extractions",
    "ExtractionsRequest",
    "ExtractionsResponse",
    "ExtractionsUsage",
    "FailableToolCallStatus",
    "FileCitation",
    "FileDeleteResponse",
    "FileListResponse",
    "FileParserPlugin",
    "FilePath",
    "FileProvider",
    "FileResponse",
    "FileSearchServerTool",
    "FilesServerTool",
    "FilesServerToolConfig",
    "Filter",
    "FinishReason",
    "ForbiddenResponse",
    "ForbiddenResponseErrorData",
    "FormatJsonObjectConfig",
    "FormatJsonSchemaConfig",
    "FormatTextConfig",
    "Formats",
    "FrameImage",
    "FreeModelDailyRequests",
    "FunctionCallArgsDeltaEvent",
    "FunctionCallArgsDoneEvent",
    "FunctionCallItem",
    "FunctionCallOutputItem",
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
    "GatewayTimeoutResponse",
    "GatewayTimeoutResponseErrorData",
    "GenerationContentData",
    "GenerationContentError",
    "GenerationContentErrorAttempt",
    "GenerationContentResponse",
    "GenerationResponse",
    "GetAnalyticsMeta200",
    "GetAnalyticsMeta401",
    "GetAnalyticsMeta403",
    "GetAnalyticsMeta500",
    "GetAnalyticsMetaParams",
    "GetApiKeyPolicyAssignment200",
    "GetApiKeyPolicyAssignment400",
    "GetApiKeyPolicyAssignment401",
    "GetApiKeyPolicyAssignment403",
    "GetApiKeyPolicyAssignment404",
    "GetApiKeyPolicyAssignment500",
    "GetApiKeyPolicyAssignmentParams",
    "GetAppRankings200",
    "GetAppRankings400",
    "GetAppRankings401",
    "GetAppRankings429",
    "GetAppRankings500",
    "GetAppRankingsParams",
    "GetBYOKKey200",
    "GetBYOKKey401",
    "GetBYOKKey403",
    "GetBYOKKey404",
    "GetBYOKKey500",
    "GetBYOKKeyParams",
    "GetBYOKKeyResponse",
    "GetBatches200",
    "GetBatches401",
    "GetBatches402",
    "GetBatches404",
    "GetBatches410",
    "GetBatches429",
    "GetBatches500",
    "GetBatches502",
    "GetBatchesParams",
    "GetBenchmarks200",
    "GetBenchmarks400",
    "GetBenchmarks401",
    "GetBenchmarks429",
    "GetBenchmarks500",
    "GetBenchmarksParams",
    "GetBudgetPolicy200",
    "GetBudgetPolicy400",
    "GetBudgetPolicy401",
    "GetBudgetPolicy403",
    "GetBudgetPolicy404",
    "GetBudgetPolicy500",
    "GetBudgetPolicyParams",
    "GetContainerFile200",
    "GetContainerFile400",
    "GetContainerFile401",
    "GetContainerFile403",
    "GetContainerFile404",
    "GetContainerFile429",
    "GetContainerFile500",
    "GetContainerFile503",
    "GetContainerFileParams",
    "GetCredits200",
    "GetCredits401",
    "GetCredits403",
    "GetCredits500",
    "GetCreditsParams",
    "GetCurrentKey200",
    "GetCurrentKey401",
    "GetCurrentKey500",
    "GetCurrentKeyParams",
    "GetExternalUser200",
    "GetExternalUser400",
    "GetExternalUser401",
    "GetExternalUser403",
    "GetExternalUser404",
    "GetExternalUser500",
    "GetExternalUserParams",
    "GetFileMetadata200",
    "GetFileMetadata401",
    "GetFileMetadata403",
    "GetFileMetadata404",
    "GetFileMetadata429",
    "GetFileMetadata500",
    "GetFileMetadata502",
    "GetFileMetadata503",
    "GetFileMetadataParams",
    "GetGeneration200",
    "GetGeneration400",
    "GetGeneration401",
    "GetGeneration402",
    "GetGeneration403",
    "GetGeneration404",
    "GetGeneration429",
    "GetGeneration500",
    "GetGeneration502",
    "GetGeneration524",
    "GetGeneration529",
    "GetGenerationParams",
    "GetGuardrail200",
    "GetGuardrail401",
    "GetGuardrail403",
    "GetGuardrail404",
    "GetGuardrail500",
    "GetGuardrailParams",
    "GetGuardrailResponse",
    "GetKey200",
    "GetKey401",
    "GetKey403",
    "GetKey404",
    "GetKey429",
    "GetKey500",
    "GetKeyParams",
    "GetMemberPolicyAssignment200",
    "GetMemberPolicyAssignment400",
    "GetMemberPolicyAssignment401",
    "GetMemberPolicyAssignment403",
    "GetMemberPolicyAssignment404",
    "GetMemberPolicyAssignment500",
    "GetMemberPolicyAssignmentParams",
    "GetModel200",
    "GetModel403",
    "GetModel404",
    "GetModel500",
    "GetModelAvailabilityPolicy200",
    "GetModelAvailabilityPolicy400",
    "GetModelAvailabilityPolicy401",
    "GetModelAvailabilityPolicy403",
    "GetModelAvailabilityPolicy404",
    "GetModelAvailabilityPolicy500",
    "GetModelAvailabilityPolicyParams",
    "GetModelParams",
    "GetModels200",
    "GetModels400",
    "GetModels401",
    "GetModels403",
    "GetModels404",
    "GetModels408",
    "GetModels409",
    "GetModels429",
    "GetModels500",
    "GetModels503",
    "GetModelsParams",
    "GetModerationPolicy200",
    "GetModerationPolicy400",
    "GetModerationPolicy401",
    "GetModerationPolicy403",
    "GetModerationPolicy404",
    "GetModerationPolicy500",
    "GetModerationPolicyParams",
    "GetObservabilityDestination200",
    "GetObservabilityDestination401",
    "GetObservabilityDestination403",
    "GetObservabilityDestination404",
    "GetObservabilityDestination500",
    "GetObservabilityDestinationParams",
    "GetObservabilityDestinationResponse",
    "GetOrganizationSettings200",
    "GetOrganizationSettings401",
    "GetOrganizationSettings403",
    "GetOrganizationSettings404",
    "GetOrganizationSettings500",
    "GetOrganizationSettingsParams",
    "GetPreset200",
    "GetPreset400",
    "GetPreset401",
    "GetPreset403",
    "GetPreset404",
    "GetPreset500",
    "GetPreset503",
    "GetPresetParams",
    "GetPresetResponse",
    "GetPresetVersion200",
    "GetPresetVersion400",
    "GetPresetVersion401",
    "GetPresetVersion403",
    "GetPresetVersion404",
    "GetPresetVersion500",
    "GetPresetVersion503",
    "GetPresetVersionParams",
    "GetPresetVersionResponse",
    "GetPrivateEndpoint200",
    "GetPrivateEndpoint401",
    "GetPrivateEndpoint403",
    "GetPrivateEndpoint404",
    "GetPrivateEndpoint408",
    "GetPrivateEndpoint500",
    "GetPrivateEndpointParams",
    "GetPrivateProvider200",
    "GetPrivateProvider401",
    "GetPrivateProvider403",
    "GetPrivateProvider404",
    "GetPrivateProvider500",
    "GetPrivateProviderParams",
    "GetRankingsDaily200",
    "GetRankingsDaily400",
    "GetRankingsDaily401",
    "GetRankingsDaily429",
    "GetRankingsDaily500",
    "GetRankingsDailyParams",
    "GetScimGroupMapping200",
    "GetScimGroupMapping401",
    "GetScimGroupMapping403",
    "GetScimGroupMapping404",
    "GetScimGroupMapping500",
    "GetScimGroupMappingParams",
    "GetScimGroupMappingResponse",
    "GetScimSyncJob200",
    "GetScimSyncJob401",
    "GetScimSyncJob403",
    "GetScimSyncJob404",
    "GetScimSyncJob500",
    "GetScimSyncJobParams",
    "GetScimSyncJobResponse",
    "GetSessionCost200",
    "GetSessionCost400",
    "GetSessionCost401",
    "GetSessionCost429",
    "GetSessionCost500",
    "GetSessionCostParams",
    "GetTaskClassifications200",
    "GetTaskClassifications400",
    "GetTaskClassifications401",
    "GetTaskClassifications429",
    "GetTaskClassifications500",
    "GetTaskClassificationsParams",
    "GetTool200",
    "GetTool401",
    "GetTool403",
    "GetTool404",
    "GetTool500",
    "GetToolParams",
    "GetToolResponse",
    "GetUserActivity200",
    "GetUserActivity400",
    "GetUserActivity401",
    "GetUserActivity403",
    "GetUserActivity404",
    "GetUserActivity500",
    "GetUserActivityParams",
    "GetVideos200",
    "GetVideos401",
    "GetVideos403",
    "GetVideos404",
    "GetVideos500",
    "GetVideosParams",
    "GetWorkspace200",
    "GetWorkspace401",
    "GetWorkspace403",
    "GetWorkspace404",
    "GetWorkspace500",
    "GetWorkspaceBudget200",
    "GetWorkspaceBudget400",
    "GetWorkspaceBudget401",
    "GetWorkspaceBudget403",
    "GetWorkspaceBudget404",
    "GetWorkspaceBudget500",
    "GetWorkspaceBudgetParams",
    "GetWorkspaceBudgetResponse",
    "GetWorkspaceParams",
    "GetWorkspaceResponse",
    "GoneResponse",
    "GoneResponseErrorData",
    "Guardrail",
    "GuardrailBudgetPolicyAuthoringConfig",
    "GuardrailBudgetPolicyConfig",
    "GuardrailDataRegion",
    "GuardrailInterval",
    "GuardrailModelAvailabilityPolicyAuthoringConfig",
    "GuardrailModelAvailabilityPolicyConfig",
    "GuardrailModerationPolicyConfig",
    "GuardrailPolicyAssignmentResponse",
    "GuardrailPolicyAssignmentState",
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
    "ImageGeneration",
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
    "IncompleteDetails",
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
    "JevRouterPlugin",
    "KeyAssignment",
    "KeyBudget",
    "Legacy_ChatContentVideo",
    "Legacy_ChatContentVideoInput",
    "Legacy_WebSearchServerTool",
    "List200",
    "List400",
    "List401",
    "List403",
    "List404",
    "List429",
    "List500",
    "ListAccountGuardrailPoliciesResponse",
    "ListAccountPolicies200",
    "ListAccountPolicies400",
    "ListAccountPolicies401",
    "ListAccountPolicies403",
    "ListAccountPolicies404",
    "ListAccountPolicies500",
    "ListAccountPoliciesParams",
    "ListBYOKKeys200",
    "ListBYOKKeys400",
    "ListBYOKKeys401",
    "ListBYOKKeys403",
    "ListBYOKKeys500",
    "ListBYOKKeysParams",
    "ListBYOKKeysResponse",
    "ListBatches200",
    "ListBatches400",
    "ListBatches401",
    "ListBatches429",
    "ListBatches500",
    "ListBatches502",
    "ListBatchesParams",
    "ListBudgetGuardrailPoliciesResponse",
    "ListBudgetPolicies200",
    "ListBudgetPolicies400",
    "ListBudgetPolicies401",
    "ListBudgetPolicies403",
    "ListBudgetPolicies404",
    "ListBudgetPolicies500",
    "ListBudgetPoliciesParams",
    "ListContainerFiles200",
    "ListContainerFiles400",
    "ListContainerFiles401",
    "ListContainerFiles403",
    "ListContainerFiles429",
    "ListContainerFiles500",
    "ListContainerFiles503",
    "ListContainerFilesParams",
    "ListCreditsPurchases200",
    "ListCreditsPurchases400",
    "ListCreditsPurchases401",
    "ListCreditsPurchases403",
    "ListCreditsPurchases404",
    "ListCreditsPurchases429",
    "ListCreditsPurchases500",
    "ListCreditsPurchases503",
    "ListCreditsPurchasesParams",
    "ListEmbeddingsModels200",
    "ListEmbeddingsModels400",
    "ListEmbeddingsModels500",
    "ListEmbeddingsModelsParams",
    "ListEndpoints200",
    "ListEndpoints403",
    "ListEndpoints404",
    "ListEndpoints500",
    "ListEndpoints503",
    "ListEndpointsParams",
    "ListEndpointsResponse",
    "ListEndpointsZdr200",
    "ListEndpointsZdr403",
    "ListEndpointsZdr500",
    "ListEndpointsZdr503",
    "ListEndpointsZdrParams",
    "ListExternalUsers200",
    "ListExternalUsers400",
    "ListExternalUsers401",
    "ListExternalUsers403",
    "ListExternalUsers404",
    "ListExternalUsers500",
    "ListExternalUsersParams",
    "ListExternalUsersResponse",
    "ListFiles200",
    "ListFiles400",
    "ListFiles401",
    "ListFiles403",
    "ListFiles429",
    "ListFiles500",
    "ListFiles502",
    "ListFiles503",
    "ListFilesParams",
    "ListGenerationContent200",
    "ListGenerationContent400",
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
    "ListGuardrailKeyAssignments403",
    "ListGuardrailKeyAssignments404",
    "ListGuardrailKeyAssignments500",
    "ListGuardrailKeyAssignmentsParams",
    "ListGuardrailMemberAssignments200",
    "ListGuardrailMemberAssignments401",
    "ListGuardrailMemberAssignments403",
    "ListGuardrailMemberAssignments404",
    "ListGuardrailMemberAssignments500",
    "ListGuardrailMemberAssignmentsParams",
    "ListGuardrails200",
    "ListGuardrails400",
    "ListGuardrails401",
    "ListGuardrails403",
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
    "ListInternConnections200",
    "ListInternConnections400",
    "ListInternConnections401",
    "ListInternConnections403",
    "ListInternConnections404",
    "ListInternConnections408",
    "ListInternConnections429",
    "ListInternConnections500",
    "ListInternConnections502",
    "ListInternConnections503",
    "ListInternConnections504",
    "ListInternConnectionsParams",
    "ListInternEffectiveVaultSecrets200",
    "ListInternEffectiveVaultSecrets400",
    "ListInternEffectiveVaultSecrets401",
    "ListInternEffectiveVaultSecrets403",
    "ListInternEffectiveVaultSecrets404",
    "ListInternEffectiveVaultSecrets408",
    "ListInternEffectiveVaultSecrets429",
    "ListInternEffectiveVaultSecrets500",
    "ListInternEffectiveVaultSecrets502",
    "ListInternEffectiveVaultSecrets503",
    "ListInternEffectiveVaultSecrets504",
    "ListInternEffectiveVaultSecretsParams",
    "ListInternVaultSecrets200",
    "ListInternVaultSecrets400",
    "ListInternVaultSecrets401",
    "ListInternVaultSecrets403",
    "ListInternVaultSecrets404",
    "ListInternVaultSecrets408",
    "ListInternVaultSecrets429",
    "ListInternVaultSecrets500",
    "ListInternVaultSecrets502",
    "ListInternVaultSecrets503",
    "ListInternVaultSecrets504",
    "ListInternVaultSecretsParams",
    "ListKeyAssignments200",
    "ListKeyAssignments400",
    "ListKeyAssignments401",
    "ListKeyAssignments403",
    "ListKeyAssignments404",
    "ListKeyAssignments500",
    "ListKeyAssignmentsParams",
    "ListKeyAssignmentsResponse",
    "ListMemberAssignments200",
    "ListMemberAssignments400",
    "ListMemberAssignments401",
    "ListMemberAssignments403",
    "ListMemberAssignments404",
    "ListMemberAssignments500",
    "ListMemberAssignmentsParams",
    "ListMemberAssignmentsResponse",
    "ListModelAvailabilityGuardrailPoliciesResponse",
    "ListModelAvailabilityPolicies200",
    "ListModelAvailabilityPolicies400",
    "ListModelAvailabilityPolicies401",
    "ListModelAvailabilityPolicies403",
    "ListModelAvailabilityPolicies404",
    "ListModelAvailabilityPolicies500",
    "ListModelAvailabilityPoliciesParams",
    "ListModelsCount200",
    "ListModelsCount400",
    "ListModelsCount403",
    "ListModelsCount500",
    "ListModelsCountParams",
    "ListModelsUser200",
    "ListModelsUser401",
    "ListModelsUser403",
    "ListModelsUser404",
    "ListModelsUser408",
    "ListModelsUser409",
    "ListModelsUser429",
    "ListModelsUser500",
    "ListModelsUser503",
    "ListModelsUserParams",
    "ListModerationGuardrailPoliciesResponse",
    "ListModerationPolicies200",
    "ListModerationPolicies400",
    "ListModerationPolicies401",
    "ListModerationPolicies403",
    "ListModerationPolicies404",
    "ListModerationPolicies500",
    "ListModerationPoliciesParams",
    "ListOauthJwks200",
    "ListOauthJwks500",
    "ListOauthJwksParams",
    "ListObservabilityDestinations200",
    "ListObservabilityDestinations400",
    "ListObservabilityDestinations401",
    "ListObservabilityDestinations403",
    "ListObservabilityDestinations500",
    "ListObservabilityDestinationsParams",
    "ListObservabilityDestinationsResponse",
    "ListOrganizationMembers200",
    "ListOrganizationMembers401",
    "ListOrganizationMembers403",
    "ListOrganizationMembers404",
    "ListOrganizationMembers500",
    "ListOrganizationMembersParams",
    "ListParams",
    "ListPresetVersions200",
    "ListPresetVersions400",
    "ListPresetVersions401",
    "ListPresetVersions403",
    "ListPresetVersions404",
    "ListPresetVersions500",
    "ListPresetVersions503",
    "ListPresetVersionsParams",
    "ListPresetVersionsResponse",
    "ListPresets200",
    "ListPresets400",
    "ListPresets401",
    "ListPresets403",
    "ListPresets404",
    "ListPresets500",
    "ListPresets503",
    "ListPresetsParams",
    "ListPresetsResponse",
    "ListPrivateEndpoints200",
    "ListPrivateEndpoints401",
    "ListPrivateEndpoints403",
    "ListPrivateEndpoints408",
    "ListPrivateEndpoints500",
    "ListPrivateEndpointsParams",
    "ListPrivateEndpointsResponse",
    "ListPrivateProviders200",
    "ListPrivateProviders401",
    "ListPrivateProviders403",
    "ListPrivateProviders500",
    "ListPrivateProvidersParams",
    "ListProviders200",
    "ListProviders500",
    "ListProvidersParams",
    "ListScimGroupMappings200",
    "ListScimGroupMappings401",
    "ListScimGroupMappings403",
    "ListScimGroupMappings404",
    "ListScimGroupMappings500",
    "ListScimGroupMappingsParams",
    "ListScimGroupMappingsResponse",
    "ListScimGroups200",
    "ListScimGroups401",
    "ListScimGroups403",
    "ListScimGroups404",
    "ListScimGroups500",
    "ListScimGroupsParams",
    "ListScimGroupsResponse",
    "ListTools200",
    "ListTools401",
    "ListTools403",
    "ListTools404",
    "ListTools500",
    "ListToolsParams",
    "ListToolsResponse",
    "ListVaultSecrets200",
    "ListVaultSecrets400",
    "ListVaultSecrets401",
    "ListVaultSecrets403",
    "ListVaultSecrets404",
    "ListVaultSecrets408",
    "ListVaultSecrets429",
    "ListVaultSecrets500",
    "ListVaultSecrets502",
    "ListVaultSecrets503",
    "ListVaultSecrets504",
    "ListVaultSecretsParams",
    "ListVideosContent400",
    "ListVideosContent401",
    "ListVideosContent403",
    "ListVideosContent404",
    "ListVideosContent409",
    "ListVideosContent410",
    "ListVideosContent500",
    "ListVideosContent502",
    "ListVideosContentParams",
    "ListVideosModels200",
    "ListVideosModels400",
    "ListVideosModels500",
    "ListVideosModelsParams",
    "ListWorkspaceBudgets200",
    "ListWorkspaceBudgets401",
    "ListWorkspaceBudgets403",
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
    "ListWorkspaces403",
    "ListWorkspaces500",
    "ListWorkspacesParams",
    "ListWorkspacesResponse",
    "LocalShellCallItem",
    "LocalShellCallOutputItem",
    "ManagedPrivateEndpoint",
    "ManagedPrivateEndpointResponse",
    "McpApprovalRequestItem",
    "McpApprovalResponseItem",
    "McpCallArgumentsDeltaEvent",
    "McpCallArgumentsDoneEvent",
    "McpCallCompletedEvent",
    "McpCallFailedEvent",
    "McpCallInProgressEvent",
    "McpCallItem",
    "McpHttpError",
    "McpListToolsCompletedEvent",
    "McpListToolsFailedEvent",
    "McpListToolsInProgressEvent",
    "McpListToolsItem",
    "McpProtocolError",
    "McpServerTool",
    "McpServerToolParameters",
    "McpServerTool_OpenRouter",
    "McpToolCallError",
    "McpToolExecutionError",
    "MemberAssignment",
    "MessagesAdvisorToolResultBlock",
    "MessagesBashToolResultBlock",
    "MessagesContentBlockDeltaEvent",
    "MessagesContentBlockStartEvent",
    "MessagesContentBlockStopEvent",
    "MessagesDeltaEvent",
    "MessagesErrorEvent",
    "MessagesFallbackParam",
    "MessagesMessageParam",
    "MessagesOutputConfig",
    "MessagesPingEvent",
    "MessagesRequest",
    "MessagesResult",
    "MessagesSearchModelsServerTool",
    "MessagesShellToolResultBlock",
    "MessagesStartEvent",
    "MessagesStopEvent",
    "MessagesStreamEvents",
    "MessagesStreamingResponse",
    "MessagesToolAdditionBlock",
    "MessagesToolRemovalBlock",
    "MetadataLevel",
    "Model",
    "ModelAliasTarget",
    "ModelArchitecture",
    "ModelAvailabilityAccountGuardrailPolicy",
    "ModelAvailabilityAccountGuardrailPolicyRequest",
    "ModelAvailabilityGuardrailPolicy",
    "ModelAvailabilityGuardrailPolicyDetail",
    "ModelAvailabilityGuardrailPolicyDetailResponse",
    "ModelAvailabilityGuardrailPolicyResponse",
    "ModelAvailabilityGuardrailPolicySummary",
    "ModelBenchmarks",
    "ModelGroup",
    "ModelLinks",
    "ModelName",
    "ModelReasoning",
    "ModelResponse",
    "ModelsCountResponse",
    "ModelsListResponse",
    "ModelsListResponseData",
    "ModerationAccountGuardrailPolicy",
    "ModerationAccountGuardrailPolicyRequest",
    "ModerationGuardrailPolicy",
    "ModerationGuardrailPolicyDetail",
    "ModerationGuardrailPolicyDetailResponse",
    "ModerationGuardrailPolicyResponse",
    "ModerationGuardrailPolicySummary",
    "ModerationPlugin",
    "MultimodalMedia",
    "NamespaceFunctionTool",
    "NamespaceTool",
    "NativeTools",
    "NotFoundResponse",
    "NotFoundResponseErrorData",
    "OAuthErrorResponse",
    "OAuthJwks",
    "ORAnthropicBashToolResult",
    "ORAnthropicContentBlock",
    "ORAnthropicNullableCaller",
    "ORAnthropicServerToolUsage",
    "ORAnthropicServerToolUseBlock",
    "ORAnthropicShellToolResult",
    "ORAnthropicStopReason",
    "ORAnthropicToolSearchResult",
    "ORAnthropicToolSearchResultParam",
    "ObservabilityArizeDestination",
    "ObservabilityBraintrustDestination",
    "ObservabilityClickhouseDestination",
    "ObservabilityDataRegion",
    "ObservabilityDataRegionInput",
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
    "OpenAIFile",
    "OpenAIFileDeleted",
    "OpenAIFileList",
    "OpenAIResponseCustomToolCall",
    "OpenAIResponseCustomToolCallOutput",
    "OpenAIResponseFunctionToolCall",
    "OpenAIResponseFunctionToolCallOutput",
    "OpenAIResponseInputMessageItem",
    "OpenAIResponsesAnnotation",
    "OpenAIResponsesRefusalContent",
    "OpenAIResponsesResponseStatus",
    "OpenAIResponsesToolChoice",
    "OpenAIResponsesTruncation",
    "OpenResponsesCreatedEvent",
    "OpenResponsesErrorMetadata",
    "OpenResponsesInProgressEvent",
    "OpenResponsesResult",
    "OpenRouterFile",
    "OpenRouterFileDeleted",
    "OpenRouterFileList",
    "OpenRouterMetadata",
    "OpenRouterWebSearchServerTool",
    "Operator",
    "OrganizationSettings",
    "OutputAdvisorServerToolItem",
    "OutputApplyPatchCallItem",
    "OutputApplyPatchServerToolItem",
    "OutputArmorBlockedItem",
    "OutputBashServerToolItem",
    "OutputBrowserUseServerToolItem",
    "OutputCodeInterpreterCallItem",
    "OutputCodeInterpreterServerToolItem",
    "OutputCompactionItem",
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
    "OutputItemApplyPatchCall",
    "OutputItemCodeInterpreterCall",
    "OutputItemCompaction",
    "OutputItemCustomToolCall",
    "OutputItemFileSearchCall",
    "OutputItemFunctionCall",
    "OutputItemImageGenerationCall",
    "OutputItemMcpApprovalRequest",
    "OutputItemMcpCall",
    "OutputItemMcpListTools",
    "OutputItemReasoning",
    "OutputItemWebSearchCall",
    "OutputItems",
    "OutputMemoryServerToolItem",
    "OutputMessage",
    "OutputMessageItem",
    "OutputModality",
    "OutputModalityEnum",
    "OutputReasoningItem",
    "OutputSearchModelsServerToolItem",
    "OutputShellCallItem",
    "OutputShellCallOutputItem",
    "OutputShellServerToolItem",
    "OutputSubagentServerToolItem",
    "OutputTextEditorServerToolItem",
    "OutputToolSearchCallItem",
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
    "PerfLast30mByWorkload",
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
    "Pricing",
    "PricingOverride",
    "PrivateEndpoint",
    "PrivateEndpointActivation",
    "PrivateEndpointCheck",
    "PrivateEndpointCheckReason",
    "PrivateEndpointDeclaredParameter",
    "PrivateEndpointDeclaredRegion",
    "PrivateEndpointParameterCheck",
    "PrivateEndpointPricing",
    "PrivateEndpointQuantization",
    "PrivateEndpointReasoningReturnMechanism",
    "PrivateEndpointResponse",
    "PrivateEndpointSettings",
    "PrivateEndpointStatus",
    "PrivateEndpointSummary",
    "PrivateEndpointValidation",
    "PrivateEndpointValidationNullable",
    "PrivateEndpointValidationResponse",
    "PrivateProvider",
    "PromoteContainerFile200",
    "PromoteContainerFile400",
    "PromoteContainerFile401",
    "PromoteContainerFile403",
    "PromoteContainerFile404",
    "PromoteContainerFile413",
    "PromoteContainerFile429",
    "PromoteContainerFile499",
    "PromoteContainerFile500",
    "PromoteContainerFile503",
    "PromoteContainerFileParams",
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
    "PublicServiceTier",
    "PublicZdrEndpoint",
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
    "Rerank",
    "ResponseHealingPlugin",
    "ResponseIncludesEnum",
    "ResponseOutputText",
    "ResponsesRequest",
    "ResponsesStreamingResponse",
    "RestorePreset200",
    "RestorePreset400",
    "RestorePreset401",
    "RestorePreset403",
    "RestorePreset404",
    "RestorePreset409",
    "RestorePreset500",
    "RestorePresetParams",
    "RouterAttempt",
    "RouterParams",
    "RoutingStrategy",
    "STT",
    "STTEntity",
    "STTInlineInputAudio",
    "STTInputAudio",
    "STTRequest",
    "STTResponse",
    "STTSegment",
    "STTTimestampGranularity",
    "STTUrlInputAudio",
    "STTUsage",
    "STTWord",
    "ScalarFilter",
    "ScalarFilterOperator",
    "ScimGroup",
    "ScimGroupMapping",
    "ScimSyncJob",
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
    "ServerTool",
    "ServerToolDetails",
    "ServerToolEngine",
    "ServerToolExecutedBy",
    "ServerToolInputName",
    "ServerToolNativeModel",
    "ServerToolNativeSupport",
    "ServerToolOutputName",
    "ServerToolPrice",
    "ServerToolUseDetails",
    "ServiceUnavailableResponse",
    "ServiceUnavailableResponseErrorData",
    "SessionCostItem",
    "SessionCostMeta",
    "SessionCostResponse",
    "SetFilter",
    "SetFilterOperator",
    "ShellCallItem",
    "ShellCallOutputContent",
    "ShellCallOutputItem",
    "ShellCallStatus",
    "ShellServerTool",
    "ShellServerToolConfig",
    "ShellServerToolEngine",
    "ShellServerToolEnvironment",
    "ShellServerTool_OpenRouter",
    "SpeechInput",
    "SpeechInputReference",
    "SpeechInputReferenceAudio",
    "SpeechInputReferenceAudioInput",
    "SpeechInputReferenceImage",
    "SpeechInputReferenceImageInput",
    "SpeechInputReferenceText",
    "SpeechRequest",
    "SpeechTurn",
    "StopServerToolsWhen",
    "StopServerToolsWhenCondition",
    "StopServerToolsWhenFinishReasonIs",
    "StopServerToolsWhenHasToolCall",
    "StopServerToolsWhenMaxCost",
    "StopServerToolsWhenMaxTokensUsed",
    "StopServerToolsWhenStepCountIs",
    "StoreInternVaultSecret200",
    "StoreInternVaultSecret400",
    "StoreInternVaultSecret401",
    "StoreInternVaultSecret403",
    "StoreInternVaultSecret404",
    "StoreInternVaultSecret408",
    "StoreInternVaultSecret409",
    "StoreInternVaultSecret413",
    "StoreInternVaultSecret429",
    "StoreInternVaultSecret500",
    "StoreInternVaultSecret502",
    "StoreInternVaultSecret503",
    "StoreInternVaultSecret504",
    "StoreInternVaultSecretParams",
    "StoreInternVaultSecretRequestJson",
    "StoreVaultSecret200",
    "StoreVaultSecret400",
    "StoreVaultSecret401",
    "StoreVaultSecret403",
    "StoreVaultSecret404",
    "StoreVaultSecret408",
    "StoreVaultSecret409",
    "StoreVaultSecret413",
    "StoreVaultSecret429",
    "StoreVaultSecret500",
    "StoreVaultSecret502",
    "StoreVaultSecret503",
    "StoreVaultSecret504",
    "StoreVaultSecretParams",
    "StoreVaultSecretRequestJson",
    "StoredPromptTemplate",
    "StreamEvents",
    "StreamEventsResponseCompleted",
    "StreamEventsResponseFailed",
    "StreamEventsResponseIncomplete",
    "StreamEventsResponseOutputItemAdded",
    "StreamEventsResponseOutputItemDone",
    "SubagentNestedTool",
    "SubagentReasoning",
    "SubagentServerToolConfig",
    "SubagentServerTool_OpenRouter",
    "SubmitGenerationFeedback200",
    "SubmitGenerationFeedback400",
    "SubmitGenerationFeedback401",
    "SubmitGenerationFeedback403",
    "SubmitGenerationFeedback404",
    "SubmitGenerationFeedback409",
    "SubmitGenerationFeedback429",
    "SubmitGenerationFeedback500",
    "SubmitGenerationFeedback503",
    "SubmitGenerationFeedbackParams",
    "SubmitGenerationFeedbackRequest",
    "SubmitGenerationFeedbackRequestJson",
    "SubmitGenerationFeedbackResponse",
    "SupportedParameters",
    "SwitchyardRouterPlugin",
    "TTS",
    "TaskClassificationItem",
    "TaskClassificationMacroCategory",
    "TaskClassificationModel",
    "TaskClassificationResponse",
    "TextDeltaEvent",
    "TextDoneEvent",
    "TextExtendedConfig",
    "TextGeneration",
    "TokenExchangeRequest",
    "TokenExchangeResponse",
    "TooManyRequestsResponse",
    "TooManyRequestsResponseErrorData",
    "ToolCallStatus",
    "ToolChoiceAllowed",
    "ToolChoiceMcp",
    "ToolChoiceSupport",
    "ToolSearchCallItem",
    "ToolSearchOutputItem",
    "ToolSearchServerTool",
    "ToolSearchServerToolConfig",
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
    "UnifiedBenchmarksORItem",
    "UnifiedBenchmarksResponse",
    "UnifiedBenchmarksSearchItem",
    "UnifiedBenchmarksSearchRunConfig",
    "Unknown",
    "UnprocessableEntityResponse",
    "UnprocessableEntityResponseErrorData",
    "UpdateAccountPolicy200",
    "UpdateAccountPolicy400",
    "UpdateAccountPolicy401",
    "UpdateAccountPolicy403",
    "UpdateAccountPolicy404",
    "UpdateAccountPolicy409",
    "UpdateAccountPolicy500",
    "UpdateAccountPolicyParams",
    "UpdateAccountPolicyRequestJson",
    "UpdateBYOKKey200",
    "UpdateBYOKKey400",
    "UpdateBYOKKey401",
    "UpdateBYOKKey403",
    "UpdateBYOKKey404",
    "UpdateBYOKKey409",
    "UpdateBYOKKey500",
    "UpdateBYOKKeyParams",
    "UpdateBYOKKeyRequest",
    "UpdateBYOKKeyRequestJson",
    "UpdateBYOKKeyResponse",
    "UpdateBudgetGuardrailPolicyRequest",
    "UpdateBudgetPolicy200",
    "UpdateBudgetPolicy400",
    "UpdateBudgetPolicy401",
    "UpdateBudgetPolicy403",
    "UpdateBudgetPolicy404",
    "UpdateBudgetPolicy409",
    "UpdateBudgetPolicy500",
    "UpdateBudgetPolicyParams",
    "UpdateBudgetPolicyRequestJson",
    "UpdateExternalUser200",
    "UpdateExternalUser400",
    "UpdateExternalUser401",
    "UpdateExternalUser404",
    "UpdateExternalUser500",
    "UpdateExternalUserParams",
    "UpdateExternalUserRequest",
    "UpdateExternalUserRequestJson",
    "UpdateGuardrail200",
    "UpdateGuardrail400",
    "UpdateGuardrail401",
    "UpdateGuardrail403",
    "UpdateGuardrail404",
    "UpdateGuardrail409",
    "UpdateGuardrail500",
    "UpdateGuardrailParams",
    "UpdateGuardrailRequest",
    "UpdateGuardrailRequestJson",
    "UpdateGuardrailResponse",
    "UpdateKeys200",
    "UpdateKeys400",
    "UpdateKeys401",
    "UpdateKeys403",
    "UpdateKeys404",
    "UpdateKeys409",
    "UpdateKeys429",
    "UpdateKeys500",
    "UpdateKeysParams",
    "UpdateKeysRequestJson",
    "UpdateModelAvailabilityGuardrailPolicyRequest",
    "UpdateModelAvailabilityPolicy200",
    "UpdateModelAvailabilityPolicy400",
    "UpdateModelAvailabilityPolicy401",
    "UpdateModelAvailabilityPolicy403",
    "UpdateModelAvailabilityPolicy404",
    "UpdateModelAvailabilityPolicy409",
    "UpdateModelAvailabilityPolicy500",
    "UpdateModelAvailabilityPolicyParams",
    "UpdateModelAvailabilityPolicyRequestJson",
    "UpdateModerationGuardrailPolicyRequest",
    "UpdateModerationPolicy200",
    "UpdateModerationPolicy400",
    "UpdateModerationPolicy401",
    "UpdateModerationPolicy403",
    "UpdateModerationPolicy404",
    "UpdateModerationPolicy409",
    "UpdateModerationPolicy500",
    "UpdateModerationPolicyParams",
    "UpdateModerationPolicyRequestJson",
    "UpdateObservabilityDestination200",
    "UpdateObservabilityDestination400",
    "UpdateObservabilityDestination401",
    "UpdateObservabilityDestination403",
    "UpdateObservabilityDestination404",
    "UpdateObservabilityDestination409",
    "UpdateObservabilityDestination500",
    "UpdateObservabilityDestinationParams",
    "UpdateObservabilityDestinationRequest",
    "UpdateObservabilityDestinationRequestJson",
    "UpdateObservabilityDestinationResponse",
    "UpdateOrganizationSettings200",
    "UpdateOrganizationSettings400",
    "UpdateOrganizationSettings401",
    "UpdateOrganizationSettings403",
    "UpdateOrganizationSettings404",
    "UpdateOrganizationSettings500",
    "UpdateOrganizationSettingsParams",
    "UpdateOrganizationSettingsRequest",
    "UpdateOrganizationSettingsRequestJson",
    "UpdatePrivateEndpoint200",
    "UpdatePrivateEndpoint400",
    "UpdatePrivateEndpoint401",
    "UpdatePrivateEndpoint403",
    "UpdatePrivateEndpoint404",
    "UpdatePrivateEndpoint408",
    "UpdatePrivateEndpoint409",
    "UpdatePrivateEndpoint422",
    "UpdatePrivateEndpoint500",
    "UpdatePrivateEndpoint502",
    "UpdatePrivateEndpointParams",
    "UpdatePrivateEndpointRequest",
    "UpdatePrivateEndpointRequestJson",
    "UpdatePrivateEndpointSettingsRequest",
    "UpdatePrivateProvider200",
    "UpdatePrivateProvider400",
    "UpdatePrivateProvider401",
    "UpdatePrivateProvider403",
    "UpdatePrivateProvider404",
    "UpdatePrivateProvider408",
    "UpdatePrivateProvider409",
    "UpdatePrivateProvider422",
    "UpdatePrivateProvider429",
    "UpdatePrivateProvider500",
    "UpdatePrivateProvider502",
    "UpdatePrivateProviderParams",
    "UpdatePrivateProviderRequest",
    "UpdatePrivateProviderRequestJson",
    "UpdateScimGroupMapping200",
    "UpdateScimGroupMapping400",
    "UpdateScimGroupMapping401",
    "UpdateScimGroupMapping403",
    "UpdateScimGroupMapping404",
    "UpdateScimGroupMapping500",
    "UpdateScimGroupMappingParams",
    "UpdateScimGroupMappingRequest",
    "UpdateScimGroupMappingRequestJson",
    "UpdateScimGroupMappingResponse",
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
    "UploadFile499",
    "UploadFile500",
    "UploadFile502",
    "UploadFile503",
    "UploadFileParams",
    "UploadFileRequestFormData",
    "UpsertWorkspaceBudget200",
    "UpsertWorkspaceBudget400",
    "UpsertWorkspaceBudget401",
    "UpsertWorkspaceBudget403",
    "UpsertWorkspaceBudget404",
    "UpsertWorkspaceBudget500",
    "UpsertWorkspaceBudgetParams",
    "UpsertWorkspaceBudgetRequest",
    "UpsertWorkspaceBudgetRequestJson",
    "UpsertWorkspaceBudgetResponse",
    "ValidatePrivateEndpoint200",
    "ValidatePrivateEndpoint400",
    "ValidatePrivateEndpoint401",
    "ValidatePrivateEndpoint403",
    "ValidatePrivateEndpoint404",
    "ValidatePrivateEndpoint408",
    "ValidatePrivateEndpoint409",
    "ValidatePrivateEndpoint422",
    "ValidatePrivateEndpoint500",
    "ValidatePrivateEndpoint502",
    "ValidatePrivateEndpointParams",
    "ValidatePrivateEndpointRequest",
    "ValidatePrivateEndpointRequestJson",
    "VaultEffectiveSecret",
    "VaultEffectiveSecretListResponse",
    "VaultRoutingTable",
    "VaultSecret",
    "VaultSecretCopyRequest",
    "VaultSecretCopyResponse",
    "VaultSecretListResponse",
    "VaultSecretResponse",
    "VaultSecretWriteRequest",
    "VideoGeneration",
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
    "WebSearchMode",
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
    "WorkspaceMember",
    "XSearchOptions",
    "__ClientMultipartFile",
]
