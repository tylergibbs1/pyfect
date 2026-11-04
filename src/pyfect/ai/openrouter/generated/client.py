"""Effect's generated ``OpenRouterClient``: a method per operation of the
OpenRouter API, generated from Effect's ``Generated.ts`` by
``scripts/gen_ai_schemas.py``; do not edit.

A JSON operation gives its decoded body (with ``include_response=True``,
the body and the response); a documented error status fails with
``OpenRouterClientError`` (``tag`` names the operation and status,
``cause`` is the decoded body). ``...Sse`` operations stream the decoded
events, ``...Stream`` ones the body's bytes.
"""

# pyright: reportPrivateUsage=false
from __future__ import annotations

import typing as _t

from pyfect import schema as _S
from pyfect._core import Effect as _Effect
from pyfect.ai import _generated_client as _c
from pyfect.encoding import sse as _sse
from pyfect.http.client import HttpClientService as _HttpClientService
from pyfect.http.error import HttpClientError as _HttpClientError
from pyfect.http.response import HttpClientResponse as _HttpClientResponse
from pyfect.stream import Stream as _Stream
from pyfect.ai.openrouter.generated import types as _T
from pyfect.ai.openrouter.generated import (
    BulkAddWorkspaceMembers200,
    BulkAddWorkspaceMembers400,
    BulkAddWorkspaceMembers401,
    BulkAddWorkspaceMembers403,
    BulkAddWorkspaceMembers404,
    BulkAddWorkspaceMembers500,
    BulkAssignKeysToGuardrail200,
    BulkAssignKeysToGuardrail400,
    BulkAssignKeysToGuardrail401,
    BulkAssignKeysToGuardrail404,
    BulkAssignKeysToGuardrail500,
    BulkAssignMembersToGuardrail200,
    BulkAssignMembersToGuardrail400,
    BulkAssignMembersToGuardrail401,
    BulkAssignMembersToGuardrail404,
    BulkAssignMembersToGuardrail500,
    BulkRemoveWorkspaceMembers200,
    BulkRemoveWorkspaceMembers400,
    BulkRemoveWorkspaceMembers401,
    BulkRemoveWorkspaceMembers403,
    BulkRemoveWorkspaceMembers404,
    BulkRemoveWorkspaceMembers500,
    BulkUnassignKeysFromGuardrail200,
    BulkUnassignKeysFromGuardrail400,
    BulkUnassignKeysFromGuardrail401,
    BulkUnassignKeysFromGuardrail404,
    BulkUnassignKeysFromGuardrail500,
    BulkUnassignMembersFromGuardrail200,
    BulkUnassignMembersFromGuardrail400,
    BulkUnassignMembersFromGuardrail401,
    BulkUnassignMembersFromGuardrail404,
    BulkUnassignMembersFromGuardrail500,
    CreateAudioSpeech400,
    CreateAudioSpeech401,
    CreateAudioSpeech402,
    CreateAudioSpeech404,
    CreateAudioSpeech429,
    CreateAudioSpeech500,
    CreateAudioSpeech502,
    CreateAudioSpeech503,
    CreateAudioSpeech524,
    CreateAudioSpeech529,
    CreateAudioTranscriptions200,
    CreateAudioTranscriptions400,
    CreateAudioTranscriptions401,
    CreateAudioTranscriptions402,
    CreateAudioTranscriptions404,
    CreateAudioTranscriptions429,
    CreateAudioTranscriptions500,
    CreateAudioTranscriptions502,
    CreateAudioTranscriptions503,
    CreateAudioTranscriptions524,
    CreateAudioTranscriptions529,
    CreateAuthKeysCode200,
    CreateAuthKeysCode400,
    CreateAuthKeysCode401,
    CreateAuthKeysCode403,
    CreateAuthKeysCode409,
    CreateAuthKeysCode500,
    CreateBYOKKey201,
    CreateBYOKKey400,
    CreateBYOKKey401,
    CreateBYOKKey403,
    CreateBYOKKey500,
    CreateCoinbaseCharge410,
    CreateEmbeddings200,
    CreateEmbeddings200Sse,
    CreateEmbeddings400,
    CreateEmbeddings401,
    CreateEmbeddings402,
    CreateEmbeddings404,
    CreateEmbeddings429,
    CreateEmbeddings500,
    CreateEmbeddings502,
    CreateEmbeddings503,
    CreateEmbeddings524,
    CreateEmbeddings529,
    CreateGuardrail201,
    CreateGuardrail400,
    CreateGuardrail401,
    CreateGuardrail403,
    CreateGuardrail500,
    CreateImages200,
    CreateImages200Sse,
    CreateImages400,
    CreateImages401,
    CreateImages402,
    CreateImages403,
    CreateImages404,
    CreateImages413,
    CreateImages429,
    CreateImages500,
    CreateImages502,
    CreateImages524,
    CreateImages529,
    CreateKeys201,
    CreateKeys400,
    CreateKeys401,
    CreateKeys403,
    CreateKeys429,
    CreateKeys500,
    CreateMessages200,
    CreateMessages200Sse,
    CreateMessages400,
    CreateMessages401,
    CreateMessages403,
    CreateMessages404,
    CreateMessages429,
    CreateMessages500,
    CreateMessages503,
    CreateMessages529,
    CreateObservabilityDestination201,
    CreateObservabilityDestination400,
    CreateObservabilityDestination401,
    CreateObservabilityDestination403,
    CreateObservabilityDestination409,
    CreateObservabilityDestination500,
    CreatePresetsChatCompletions200,
    CreatePresetsChatCompletions400,
    CreatePresetsChatCompletions401,
    CreatePresetsChatCompletions403,
    CreatePresetsChatCompletions404,
    CreatePresetsChatCompletions409,
    CreatePresetsChatCompletions500,
    CreatePresetsMessages200,
    CreatePresetsMessages400,
    CreatePresetsMessages401,
    CreatePresetsMessages403,
    CreatePresetsMessages404,
    CreatePresetsMessages409,
    CreatePresetsMessages500,
    CreatePresetsResponses200,
    CreatePresetsResponses400,
    CreatePresetsResponses401,
    CreatePresetsResponses403,
    CreatePresetsResponses404,
    CreatePresetsResponses409,
    CreatePresetsResponses500,
    CreateRerank200,
    CreateRerank200Sse,
    CreateRerank400,
    CreateRerank401,
    CreateRerank402,
    CreateRerank404,
    CreateRerank429,
    CreateRerank500,
    CreateRerank502,
    CreateRerank503,
    CreateRerank524,
    CreateRerank529,
    CreateResponses200,
    CreateResponses200Sse,
    CreateResponses400,
    CreateResponses401,
    CreateResponses402,
    CreateResponses403,
    CreateResponses404,
    CreateResponses408,
    CreateResponses413,
    CreateResponses422,
    CreateResponses429,
    CreateResponses500,
    CreateResponses502,
    CreateResponses503,
    CreateResponses524,
    CreateResponses529,
    CreateVideos202,
    CreateVideos400,
    CreateVideos401,
    CreateVideos402,
    CreateVideos404,
    CreateVideos429,
    CreateVideos500,
    CreateWorkspace201,
    CreateWorkspace400,
    CreateWorkspace401,
    CreateWorkspace403,
    CreateWorkspace500,
    DeleteBYOKKey200,
    DeleteBYOKKey401,
    DeleteBYOKKey404,
    DeleteBYOKKey500,
    DeleteFile200,
    DeleteFile401,
    DeleteFile404,
    DeleteFile429,
    DeleteFile500,
    DeleteGuardrail200,
    DeleteGuardrail401,
    DeleteGuardrail404,
    DeleteGuardrail500,
    DeleteKeys200,
    DeleteKeys401,
    DeleteKeys404,
    DeleteKeys429,
    DeleteKeys500,
    DeleteObservabilityDestination200,
    DeleteObservabilityDestination401,
    DeleteObservabilityDestination404,
    DeleteObservabilityDestination500,
    DeleteWorkspace200,
    DeleteWorkspace400,
    DeleteWorkspace401,
    DeleteWorkspace403,
    DeleteWorkspace404,
    DeleteWorkspace500,
    DeleteWorkspaceBudget200,
    DeleteWorkspaceBudget401,
    DeleteWorkspaceBudget404,
    DeleteWorkspaceBudget500,
    DownloadFileContent400,
    DownloadFileContent401,
    DownloadFileContent404,
    DownloadFileContent429,
    DownloadFileContent500,
    ExchangeAuthCodeForAPIKey200,
    ExchangeAuthCodeForAPIKey400,
    ExchangeAuthCodeForAPIKey403,
    ExchangeAuthCodeForAPIKey500,
    GetAnalyticsMeta200,
    GetAnalyticsMeta401,
    GetAnalyticsMeta403,
    GetAnalyticsMeta500,
    GetAppRankings200,
    GetAppRankings400,
    GetAppRankings401,
    GetAppRankings429,
    GetAppRankings500,
    GetBYOKKey200,
    GetBYOKKey401,
    GetBYOKKey404,
    GetBYOKKey500,
    GetBenchmarks200,
    GetBenchmarks400,
    GetBenchmarks401,
    GetBenchmarks429,
    GetBenchmarks500,
    GetCredits200,
    GetCredits401,
    GetCredits403,
    GetCredits500,
    GetCurrentKey200,
    GetCurrentKey401,
    GetCurrentKey500,
    GetFileMetadata200,
    GetFileMetadata401,
    GetFileMetadata404,
    GetFileMetadata429,
    GetFileMetadata500,
    GetGeneration200,
    GetGeneration401,
    GetGeneration402,
    GetGeneration404,
    GetGeneration429,
    GetGeneration500,
    GetGeneration502,
    GetGeneration524,
    GetGeneration529,
    GetGuardrail200,
    GetGuardrail401,
    GetGuardrail404,
    GetGuardrail500,
    GetKey200,
    GetKey401,
    GetKey404,
    GetKey429,
    GetKey500,
    GetModel200,
    GetModel403,
    GetModel404,
    GetModel500,
    GetModels200,
    GetModels400,
    GetModels403,
    GetModels500,
    GetObservabilityDestination200,
    GetObservabilityDestination401,
    GetObservabilityDestination404,
    GetObservabilityDestination500,
    GetPreset200,
    GetPreset400,
    GetPreset401,
    GetPreset404,
    GetPreset500,
    GetPresetVersion200,
    GetPresetVersion400,
    GetPresetVersion401,
    GetPresetVersion404,
    GetPresetVersion500,
    GetRankingsDaily200,
    GetRankingsDaily400,
    GetRankingsDaily401,
    GetRankingsDaily429,
    GetRankingsDaily500,
    GetTaskClassifications200,
    GetTaskClassifications400,
    GetTaskClassifications401,
    GetTaskClassifications429,
    GetTaskClassifications500,
    GetUserActivity200,
    GetUserActivity400,
    GetUserActivity401,
    GetUserActivity403,
    GetUserActivity404,
    GetUserActivity500,
    GetVideos200,
    GetVideos401,
    GetVideos404,
    GetVideos500,
    GetWorkspace200,
    GetWorkspace401,
    GetWorkspace404,
    GetWorkspace500,
    List200,
    List400,
    List401,
    List429,
    List500,
    ListBYOKKeys200,
    ListBYOKKeys400,
    ListBYOKKeys401,
    ListBYOKKeys500,
    ListEmbeddingsModels200,
    ListEmbeddingsModels400,
    ListEmbeddingsModels500,
    ListEndpoints200,
    ListEndpoints403,
    ListEndpoints404,
    ListEndpoints500,
    ListEndpointsZdr200,
    ListEndpointsZdr403,
    ListEndpointsZdr500,
    ListFiles200,
    ListFiles400,
    ListFiles401,
    ListFiles429,
    ListFiles500,
    ListGenerationContent200,
    ListGenerationContent401,
    ListGenerationContent403,
    ListGenerationContent404,
    ListGenerationContent429,
    ListGenerationContent500,
    ListGenerationContent502,
    ListGenerationContent524,
    ListGenerationContent529,
    ListGuardrailKeyAssignments200,
    ListGuardrailKeyAssignments401,
    ListGuardrailKeyAssignments404,
    ListGuardrailKeyAssignments500,
    ListGuardrailMemberAssignments200,
    ListGuardrailMemberAssignments401,
    ListGuardrailMemberAssignments404,
    ListGuardrailMemberAssignments500,
    ListGuardrails200,
    ListGuardrails400,
    ListGuardrails401,
    ListGuardrails500,
    ListImageModelEndpoints200,
    ListImageModelEndpoints404,
    ListImageModelEndpoints500,
    ListImageModels200,
    ListImageModels500,
    ListKeyAssignments200,
    ListKeyAssignments401,
    ListKeyAssignments500,
    ListMemberAssignments200,
    ListMemberAssignments401,
    ListMemberAssignments500,
    ListModelsCount200,
    ListModelsCount400,
    ListModelsCount403,
    ListModelsCount500,
    ListModelsUser200,
    ListModelsUser401,
    ListModelsUser403,
    ListModelsUser404,
    ListModelsUser500,
    ListObservabilityDestinations200,
    ListObservabilityDestinations400,
    ListObservabilityDestinations401,
    ListObservabilityDestinations500,
    ListOrganizationMembers200,
    ListOrganizationMembers401,
    ListOrganizationMembers404,
    ListOrganizationMembers500,
    ListPresetVersions200,
    ListPresetVersions400,
    ListPresetVersions401,
    ListPresetVersions404,
    ListPresetVersions500,
    ListPresets200,
    ListPresets400,
    ListPresets401,
    ListPresets500,
    ListProviders200,
    ListProviders500,
    ListVideosContent400,
    ListVideosContent401,
    ListVideosContent404,
    ListVideosContent500,
    ListVideosContent502,
    ListVideosModels200,
    ListVideosModels400,
    ListVideosModels500,
    ListWorkspaceBudgets200,
    ListWorkspaceBudgets401,
    ListWorkspaceBudgets404,
    ListWorkspaceBudgets500,
    ListWorkspaceMembers200,
    ListWorkspaceMembers401,
    ListWorkspaceMembers403,
    ListWorkspaceMembers404,
    ListWorkspaceMembers500,
    ListWorkspaces200,
    ListWorkspaces401,
    ListWorkspaces500,
    QueryAnalytics200,
    QueryAnalytics400,
    QueryAnalytics401,
    QueryAnalytics403,
    QueryAnalytics408,
    QueryAnalytics500,
    SendChatCompletionRequest200,
    SendChatCompletionRequest200Sse,
    SendChatCompletionRequest400,
    SendChatCompletionRequest401,
    SendChatCompletionRequest402,
    SendChatCompletionRequest403,
    SendChatCompletionRequest404,
    SendChatCompletionRequest408,
    SendChatCompletionRequest413,
    SendChatCompletionRequest422,
    SendChatCompletionRequest429,
    SendChatCompletionRequest500,
    SendChatCompletionRequest502,
    SendChatCompletionRequest503,
    SendChatCompletionRequest524,
    SendChatCompletionRequest529,
    SubmitGenerationFeedback200,
    SubmitGenerationFeedback400,
    SubmitGenerationFeedback401,
    SubmitGenerationFeedback404,
    SubmitGenerationFeedback429,
    SubmitGenerationFeedback500,
    UpdateBYOKKey200,
    UpdateBYOKKey400,
    UpdateBYOKKey401,
    UpdateBYOKKey404,
    UpdateBYOKKey500,
    UpdateGuardrail200,
    UpdateGuardrail400,
    UpdateGuardrail401,
    UpdateGuardrail404,
    UpdateGuardrail500,
    UpdateKeys200,
    UpdateKeys400,
    UpdateKeys401,
    UpdateKeys404,
    UpdateKeys429,
    UpdateKeys500,
    UpdateObservabilityDestination200,
    UpdateObservabilityDestination400,
    UpdateObservabilityDestination401,
    UpdateObservabilityDestination404,
    UpdateObservabilityDestination409,
    UpdateObservabilityDestination500,
    UpdateWorkspace200,
    UpdateWorkspace400,
    UpdateWorkspace401,
    UpdateWorkspace403,
    UpdateWorkspace404,
    UpdateWorkspace500,
    UploadFile200,
    UploadFile400,
    UploadFile401,
    UploadFile403,
    UploadFile413,
    UploadFile429,
    UploadFile500,
    UpsertWorkspaceBudget200,
    UpsertWorkspaceBudget400,
    UpsertWorkspaceBudget401,
    UpsertWorkspaceBudget404,
    UpsertWorkspaceBudget500,
)


class OpenRouterClientError(_c.ClientError):
    """A documented error status of an operation."""


type _Errors = _HttpClientError | _S.SchemaError | OpenRouterClientError
type _PlainErrors = _HttpClientError | _S.SchemaError
type _SseErrors = _HttpClientError | _S.SchemaError | _sse.Retry | _sse.SseError

_GET_USER_ACTIVITY = _c.Operation("GET", url_params=('date', 'api_key_hash', 'user_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetUserActivity200, errors={400: ('GetUserActivity400', GetUserActivity400), 401: ('GetUserActivity401', GetUserActivity401), 403: ('GetUserActivity403', GetUserActivity403), 404: ('GetUserActivity404', GetUserActivity404), 500: ('GetUserActivity500', GetUserActivity500)})
_GET_ANALYTICS_META = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetAnalyticsMeta200, errors={401: ('GetAnalyticsMeta401', GetAnalyticsMeta401), 403: ('GetAnalyticsMeta403', GetAnalyticsMeta403), 500: ('GetAnalyticsMeta500', GetAnalyticsMeta500)})
_QUERY_ANALYTICS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=QueryAnalytics200, errors={400: ('QueryAnalytics400', QueryAnalytics400), 401: ('QueryAnalytics401', QueryAnalytics401), 403: ('QueryAnalytics403', QueryAnalytics403), 408: ('QueryAnalytics408', QueryAnalytics408), 500: ('QueryAnalytics500', QueryAnalytics500)})
_CREATE_AUDIO_SPEECH = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), errors={400: ('CreateAudioSpeech400', CreateAudioSpeech400), 401: ('CreateAudioSpeech401', CreateAudioSpeech401), 402: ('CreateAudioSpeech402', CreateAudioSpeech402), 404: ('CreateAudioSpeech404', CreateAudioSpeech404), 429: ('CreateAudioSpeech429', CreateAudioSpeech429), 500: ('CreateAudioSpeech500', CreateAudioSpeech500), 502: ('CreateAudioSpeech502', CreateAudioSpeech502), 503: ('CreateAudioSpeech503', CreateAudioSpeech503), 524: ('CreateAudioSpeech524', CreateAudioSpeech524), 529: ('CreateAudioSpeech529', CreateAudioSpeech529)})
_CREATE_AUDIO_TRANSCRIPTIONS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateAudioTranscriptions200, errors={400: ('CreateAudioTranscriptions400', CreateAudioTranscriptions400), 401: ('CreateAudioTranscriptions401', CreateAudioTranscriptions401), 402: ('CreateAudioTranscriptions402', CreateAudioTranscriptions402), 404: ('CreateAudioTranscriptions404', CreateAudioTranscriptions404), 429: ('CreateAudioTranscriptions429', CreateAudioTranscriptions429), 500: ('CreateAudioTranscriptions500', CreateAudioTranscriptions500), 502: ('CreateAudioTranscriptions502', CreateAudioTranscriptions502), 503: ('CreateAudioTranscriptions503', CreateAudioTranscriptions503), 524: ('CreateAudioTranscriptions524', CreateAudioTranscriptions524), 529: ('CreateAudioTranscriptions529', CreateAudioTranscriptions529)})
_EXCHANGE_AUTH_CODE_FOR_API_KEY = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ExchangeAuthCodeForAPIKey200, errors={400: ('ExchangeAuthCodeForAPIKey400', ExchangeAuthCodeForAPIKey400), 403: ('ExchangeAuthCodeForAPIKey403', ExchangeAuthCodeForAPIKey403), 500: ('ExchangeAuthCodeForAPIKey500', ExchangeAuthCodeForAPIKey500)})
_CREATE_AUTH_KEYS_CODE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateAuthKeysCode200, errors={400: ('CreateAuthKeysCode400', CreateAuthKeysCode400), 401: ('CreateAuthKeysCode401', CreateAuthKeysCode401), 403: ('CreateAuthKeysCode403', CreateAuthKeysCode403), 409: ('CreateAuthKeysCode409', CreateAuthKeysCode409), 500: ('CreateAuthKeysCode500', CreateAuthKeysCode500)})
_GET_BENCHMARKS = _c.Operation("GET", url_params=('source', 'task_type', 'arena', 'category', 'max_results', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetBenchmarks200, errors={400: ('GetBenchmarks400', GetBenchmarks400), 401: ('GetBenchmarks401', GetBenchmarks401), 429: ('GetBenchmarks429', GetBenchmarks429), 500: ('GetBenchmarks500', GetBenchmarks500)})
_LIST_BYOK_KEYS = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', 'provider', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListBYOKKeys200, errors={400: ('ListBYOKKeys400', ListBYOKKeys400), 401: ('ListBYOKKeys401', ListBYOKKeys401), 500: ('ListBYOKKeys500', ListBYOKKeys500)})
_CREATE_BYOK_KEY = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateBYOKKey201, errors={400: ('CreateBYOKKey400', CreateBYOKKey400), 401: ('CreateBYOKKey401', CreateBYOKKey401), 403: ('CreateBYOKKey403', CreateBYOKKey403), 500: ('CreateBYOKKey500', CreateBYOKKey500)})
_GET_BYOK_KEY = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetBYOKKey200, errors={401: ('GetBYOKKey401', GetBYOKKey401), 404: ('GetBYOKKey404', GetBYOKKey404), 500: ('GetBYOKKey500', GetBYOKKey500)})
_DELETE_BYOK_KEY = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteBYOKKey200, errors={401: ('DeleteBYOKKey401', DeleteBYOKKey401), 404: ('DeleteBYOKKey404', DeleteBYOKKey404), 500: ('DeleteBYOKKey500', DeleteBYOKKey500)})
_UPDATE_BYOK_KEY = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateBYOKKey200, errors={400: ('UpdateBYOKKey400', UpdateBYOKKey400), 401: ('UpdateBYOKKey401', UpdateBYOKKey401), 404: ('UpdateBYOKKey404', UpdateBYOKKey404), 500: ('UpdateBYOKKey500', UpdateBYOKKey500)})
_SEND_CHAT_COMPLETION_REQUEST = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ), success=SendChatCompletionRequest200, errors={400: ('SendChatCompletionRequest400', SendChatCompletionRequest400), 401: ('SendChatCompletionRequest401', SendChatCompletionRequest401), 402: ('SendChatCompletionRequest402', SendChatCompletionRequest402), 403: ('SendChatCompletionRequest403', SendChatCompletionRequest403), 404: ('SendChatCompletionRequest404', SendChatCompletionRequest404), 408: ('SendChatCompletionRequest408', SendChatCompletionRequest408), 413: ('SendChatCompletionRequest413', SendChatCompletionRequest413), 422: ('SendChatCompletionRequest422', SendChatCompletionRequest422), 429: ('SendChatCompletionRequest429', SendChatCompletionRequest429), 500: ('SendChatCompletionRequest500', SendChatCompletionRequest500), 502: ('SendChatCompletionRequest502', SendChatCompletionRequest502), 503: ('SendChatCompletionRequest503', SendChatCompletionRequest503), 524: ('SendChatCompletionRequest524', SendChatCompletionRequest524), 529: ('SendChatCompletionRequest529', SendChatCompletionRequest529)})
_SEND_CHAT_COMPLETION_REQUEST_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ))
_GET_TASK_CLASSIFICATIONS = _c.Operation("GET", url_params=('window', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetTaskClassifications200, errors={400: ('GetTaskClassifications400', GetTaskClassifications400), 401: ('GetTaskClassifications401', GetTaskClassifications401), 429: ('GetTaskClassifications429', GetTaskClassifications429), 500: ('GetTaskClassifications500', GetTaskClassifications500)})
_GET_CREDITS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetCredits200, errors={401: ('GetCredits401', GetCredits401), 403: ('GetCredits403', GetCredits403), 500: ('GetCredits500', GetCredits500)})
_CREATE_COINBASE_CHARGE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), void=(200, ), errors={410: ('CreateCoinbaseCharge410', CreateCoinbaseCharge410)})
_GET_APP_RANKINGS = _c.Operation("GET", url_params=('category', 'subcategory', 'sort', 'start_date', 'end_date', 'limit', 'offset', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetAppRankings200, errors={400: ('GetAppRankings400', GetAppRankings400), 401: ('GetAppRankings401', GetAppRankings401), 429: ('GetAppRankings429', GetAppRankings429), 500: ('GetAppRankings500', GetAppRankings500)})
_GET_RANKINGS_DAILY = _c.Operation("GET", url_params=('start_date', 'end_date', 'period', 'modality', 'context_bucket', 'category', 'language_type', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetRankingsDaily200, errors={400: ('GetRankingsDaily400', GetRankingsDaily400), 401: ('GetRankingsDaily401', GetRankingsDaily401), 429: ('GetRankingsDaily429', GetRankingsDaily429), 500: ('GetRankingsDaily500', GetRankingsDaily500)})
_CREATE_EMBEDDINGS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateEmbeddings200, errors={400: ('CreateEmbeddings400', CreateEmbeddings400), 401: ('CreateEmbeddings401', CreateEmbeddings401), 402: ('CreateEmbeddings402', CreateEmbeddings402), 404: ('CreateEmbeddings404', CreateEmbeddings404), 429: ('CreateEmbeddings429', CreateEmbeddings429), 500: ('CreateEmbeddings500', CreateEmbeddings500), 502: ('CreateEmbeddings502', CreateEmbeddings502), 503: ('CreateEmbeddings503', CreateEmbeddings503), 524: ('CreateEmbeddings524', CreateEmbeddings524), 529: ('CreateEmbeddings529', CreateEmbeddings529)})
_CREATE_EMBEDDINGS_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_LIST_EMBEDDINGS_MODELS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListEmbeddingsModels200, errors={400: ('ListEmbeddingsModels400', ListEmbeddingsModels400), 500: ('ListEmbeddingsModels500', ListEmbeddingsModels500)})
_LIST_ENDPOINTS_ZDR = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListEndpointsZdr200, errors={403: ('ListEndpointsZdr403', ListEndpointsZdr403), 500: ('ListEndpointsZdr500', ListEndpointsZdr500)})
_LIST_FILES = _c.Operation("GET", url_params=('limit', 'cursor', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListFiles200, errors={400: ('ListFiles400', ListFiles400), 401: ('ListFiles401', ListFiles401), 429: ('ListFiles429', ListFiles429), 500: ('ListFiles500', ListFiles500)})
_UPLOAD_FILE = _c.Operation("POST", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UploadFile200, errors={400: ('UploadFile400', UploadFile400), 401: ('UploadFile401', UploadFile401), 403: ('UploadFile403', UploadFile403), 413: ('UploadFile413', UploadFile413), 429: ('UploadFile429', UploadFile429), 500: ('UploadFile500', UploadFile500)})
_GET_FILE_METADATA = _c.Operation("GET", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetFileMetadata200, errors={401: ('GetFileMetadata401', GetFileMetadata401), 404: ('GetFileMetadata404', GetFileMetadata404), 429: ('GetFileMetadata429', GetFileMetadata429), 500: ('GetFileMetadata500', GetFileMetadata500)})
_DELETE_FILE = _c.Operation("DELETE", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteFile200, errors={401: ('DeleteFile401', DeleteFile401), 404: ('DeleteFile404', DeleteFile404), 429: ('DeleteFile429', DeleteFile429), 500: ('DeleteFile500', DeleteFile500)})
_DOWNLOAD_FILE_CONTENT = _c.Operation("GET", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), errors={400: ('DownloadFileContent400', DownloadFileContent400), 401: ('DownloadFileContent401', DownloadFileContent401), 404: ('DownloadFileContent404', DownloadFileContent404), 429: ('DownloadFileContent429', DownloadFileContent429), 500: ('DownloadFileContent500', DownloadFileContent500)})
_DOWNLOAD_FILE_CONTENT_STREAM = _c.Operation("GET", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_GET_GENERATION = _c.Operation("GET", url_params=('id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetGeneration200, errors={401: ('GetGeneration401', GetGeneration401), 402: ('GetGeneration402', GetGeneration402), 404: ('GetGeneration404', GetGeneration404), 429: ('GetGeneration429', GetGeneration429), 500: ('GetGeneration500', GetGeneration500), 502: ('GetGeneration502', GetGeneration502), 524: ('GetGeneration524', GetGeneration524), 529: ('GetGeneration529', GetGeneration529)})
_LIST_GENERATION_CONTENT = _c.Operation("GET", url_params=('id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListGenerationContent200, errors={401: ('ListGenerationContent401', ListGenerationContent401), 403: ('ListGenerationContent403', ListGenerationContent403), 404: ('ListGenerationContent404', ListGenerationContent404), 429: ('ListGenerationContent429', ListGenerationContent429), 500: ('ListGenerationContent500', ListGenerationContent500), 502: ('ListGenerationContent502', ListGenerationContent502), 524: ('ListGenerationContent524', ListGenerationContent524), 529: ('ListGenerationContent529', ListGenerationContent529)})
_SUBMIT_GENERATION_FEEDBACK = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=SubmitGenerationFeedback200, errors={400: ('SubmitGenerationFeedback400', SubmitGenerationFeedback400), 401: ('SubmitGenerationFeedback401', SubmitGenerationFeedback401), 404: ('SubmitGenerationFeedback404', SubmitGenerationFeedback404), 429: ('SubmitGenerationFeedback429', SubmitGenerationFeedback429), 500: ('SubmitGenerationFeedback500', SubmitGenerationFeedback500)})
_LIST_GUARDRAILS = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListGuardrails200, errors={400: ('ListGuardrails400', ListGuardrails400), 401: ('ListGuardrails401', ListGuardrails401), 500: ('ListGuardrails500', ListGuardrails500)})
_CREATE_GUARDRAIL = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateGuardrail201, errors={400: ('CreateGuardrail400', CreateGuardrail400), 401: ('CreateGuardrail401', CreateGuardrail401), 403: ('CreateGuardrail403', CreateGuardrail403), 500: ('CreateGuardrail500', CreateGuardrail500)})
_GET_GUARDRAIL = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetGuardrail200, errors={401: ('GetGuardrail401', GetGuardrail401), 404: ('GetGuardrail404', GetGuardrail404), 500: ('GetGuardrail500', GetGuardrail500)})
_DELETE_GUARDRAIL = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteGuardrail200, errors={401: ('DeleteGuardrail401', DeleteGuardrail401), 404: ('DeleteGuardrail404', DeleteGuardrail404), 500: ('DeleteGuardrail500', DeleteGuardrail500)})
_UPDATE_GUARDRAIL = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateGuardrail200, errors={400: ('UpdateGuardrail400', UpdateGuardrail400), 401: ('UpdateGuardrail401', UpdateGuardrail401), 404: ('UpdateGuardrail404', UpdateGuardrail404), 500: ('UpdateGuardrail500', UpdateGuardrail500)})
_LIST_GUARDRAIL_KEY_ASSIGNMENTS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListGuardrailKeyAssignments200, errors={401: ('ListGuardrailKeyAssignments401', ListGuardrailKeyAssignments401), 404: ('ListGuardrailKeyAssignments404', ListGuardrailKeyAssignments404), 500: ('ListGuardrailKeyAssignments500', ListGuardrailKeyAssignments500)})
_BULK_ASSIGN_KEYS_TO_GUARDRAIL = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkAssignKeysToGuardrail200, errors={400: ('BulkAssignKeysToGuardrail400', BulkAssignKeysToGuardrail400), 401: ('BulkAssignKeysToGuardrail401', BulkAssignKeysToGuardrail401), 404: ('BulkAssignKeysToGuardrail404', BulkAssignKeysToGuardrail404), 500: ('BulkAssignKeysToGuardrail500', BulkAssignKeysToGuardrail500)})
_BULK_UNASSIGN_KEYS_FROM_GUARDRAIL = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkUnassignKeysFromGuardrail200, errors={400: ('BulkUnassignKeysFromGuardrail400', BulkUnassignKeysFromGuardrail400), 401: ('BulkUnassignKeysFromGuardrail401', BulkUnassignKeysFromGuardrail401), 404: ('BulkUnassignKeysFromGuardrail404', BulkUnassignKeysFromGuardrail404), 500: ('BulkUnassignKeysFromGuardrail500', BulkUnassignKeysFromGuardrail500)})
_LIST_GUARDRAIL_MEMBER_ASSIGNMENTS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListGuardrailMemberAssignments200, errors={401: ('ListGuardrailMemberAssignments401', ListGuardrailMemberAssignments401), 404: ('ListGuardrailMemberAssignments404', ListGuardrailMemberAssignments404), 500: ('ListGuardrailMemberAssignments500', ListGuardrailMemberAssignments500)})
_BULK_ASSIGN_MEMBERS_TO_GUARDRAIL = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkAssignMembersToGuardrail200, errors={400: ('BulkAssignMembersToGuardrail400', BulkAssignMembersToGuardrail400), 401: ('BulkAssignMembersToGuardrail401', BulkAssignMembersToGuardrail401), 404: ('BulkAssignMembersToGuardrail404', BulkAssignMembersToGuardrail404), 500: ('BulkAssignMembersToGuardrail500', BulkAssignMembersToGuardrail500)})
_BULK_UNASSIGN_MEMBERS_FROM_GUARDRAIL = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkUnassignMembersFromGuardrail200, errors={400: ('BulkUnassignMembersFromGuardrail400', BulkUnassignMembersFromGuardrail400), 401: ('BulkUnassignMembersFromGuardrail401', BulkUnassignMembersFromGuardrail401), 404: ('BulkUnassignMembersFromGuardrail404', BulkUnassignMembersFromGuardrail404), 500: ('BulkUnassignMembersFromGuardrail500', BulkUnassignMembersFromGuardrail500)})
_LIST_KEY_ASSIGNMENTS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListKeyAssignments200, errors={401: ('ListKeyAssignments401', ListKeyAssignments401), 500: ('ListKeyAssignments500', ListKeyAssignments500)})
_LIST_MEMBER_ASSIGNMENTS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListMemberAssignments200, errors={401: ('ListMemberAssignments401', ListMemberAssignments401), 500: ('ListMemberAssignments500', ListMemberAssignments500)})
_CREATE_IMAGES = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateImages200, errors={400: ('CreateImages400', CreateImages400), 401: ('CreateImages401', CreateImages401), 402: ('CreateImages402', CreateImages402), 403: ('CreateImages403', CreateImages403), 404: ('CreateImages404', CreateImages404), 413: ('CreateImages413', CreateImages413), 429: ('CreateImages429', CreateImages429), 500: ('CreateImages500', CreateImages500), 502: ('CreateImages502', CreateImages502), 524: ('CreateImages524', CreateImages524), 529: ('CreateImages529', CreateImages529)})
_CREATE_IMAGES_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_LIST_IMAGE_MODELS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListImageModels200, errors={500: ('ListImageModels500', ListImageModels500)})
_LIST_IMAGE_MODEL_ENDPOINTS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListImageModelEndpoints200, errors={404: ('ListImageModelEndpoints404', ListImageModelEndpoints404), 500: ('ListImageModelEndpoints500', ListImageModelEndpoints500)})
_GET_CURRENT_KEY = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetCurrentKey200, errors={401: ('GetCurrentKey401', GetCurrentKey401), 500: ('GetCurrentKey500', GetCurrentKey500)})
_LIST = _c.Operation("GET", url_params=('include_disabled', 'offset', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=List200, errors={400: ('List400', List400), 401: ('List401', List401), 429: ('List429', List429), 500: ('List500', List500)})
_CREATE_KEYS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateKeys201, errors={400: ('CreateKeys400', CreateKeys400), 401: ('CreateKeys401', CreateKeys401), 403: ('CreateKeys403', CreateKeys403), 429: ('CreateKeys429', CreateKeys429), 500: ('CreateKeys500', CreateKeys500)})
_GET_KEY = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetKey200, errors={401: ('GetKey401', GetKey401), 404: ('GetKey404', GetKey404), 429: ('GetKey429', GetKey429), 500: ('GetKey500', GetKey500)})
_DELETE_KEYS = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteKeys200, errors={401: ('DeleteKeys401', DeleteKeys401), 404: ('DeleteKeys404', DeleteKeys404), 429: ('DeleteKeys429', DeleteKeys429), 500: ('DeleteKeys500', DeleteKeys500)})
_UPDATE_KEYS = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateKeys200, errors={400: ('UpdateKeys400', UpdateKeys400), 401: ('UpdateKeys401', UpdateKeys401), 404: ('UpdateKeys404', UpdateKeys404), 429: ('UpdateKeys429', UpdateKeys429), 500: ('UpdateKeys500', UpdateKeys500)})
_CREATE_MESSAGES = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ), success=CreateMessages200, errors={400: ('CreateMessages400', CreateMessages400), 401: ('CreateMessages401', CreateMessages401), 403: ('CreateMessages403', CreateMessages403), 404: ('CreateMessages404', CreateMessages404), 429: ('CreateMessages429', CreateMessages429), 500: ('CreateMessages500', CreateMessages500), 503: ('CreateMessages503', CreateMessages503), 529: ('CreateMessages529', CreateMessages529)})
_CREATE_MESSAGES_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ))
_GET_MODEL = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetModel200, errors={403: ('GetModel403', GetModel403), 404: ('GetModel404', GetModel404), 500: ('GetModel500', GetModel500)})
_GET_MODELS = _c.Operation("GET", url_params=('offset', 'limit', 'category', 'supported_parameters', 'output_modalities', 'sort', 'q', 'input_modalities', 'context', 'min_price', 'max_price', 'arch', 'model_authors', 'providers', 'distillable', 'zdr', 'region', 'min_output_price', 'max_output_price', 'min_age_days', 'max_age_days', 'min_intelligence_index', 'max_intelligence_index', 'min_coding_index', 'max_coding_index', 'min_agentic_index', 'max_agentic_index', 'min_tool_success_rate', 'max_tool_success_rate', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetModels200, errors={400: ('GetModels400', GetModels400), 403: ('GetModels403', GetModels403), 500: ('GetModels500', GetModels500)})
_LIST_ENDPOINTS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListEndpoints200, errors={403: ('ListEndpoints403', ListEndpoints403), 404: ('ListEndpoints404', ListEndpoints404), 500: ('ListEndpoints500', ListEndpoints500)})
_LIST_MODELS_COUNT = _c.Operation("GET", url_params=('output_modalities', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListModelsCount200, errors={400: ('ListModelsCount400', ListModelsCount400), 403: ('ListModelsCount403', ListModelsCount403), 500: ('ListModelsCount500', ListModelsCount500)})
_LIST_MODELS_USER = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListModelsUser200, errors={401: ('ListModelsUser401', ListModelsUser401), 403: ('ListModelsUser403', ListModelsUser403), 404: ('ListModelsUser404', ListModelsUser404), 500: ('ListModelsUser500', ListModelsUser500)})
_LIST_OBSERVABILITY_DESTINATIONS = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListObservabilityDestinations200, errors={400: ('ListObservabilityDestinations400', ListObservabilityDestinations400), 401: ('ListObservabilityDestinations401', ListObservabilityDestinations401), 500: ('ListObservabilityDestinations500', ListObservabilityDestinations500)})
_CREATE_OBSERVABILITY_DESTINATION = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateObservabilityDestination201, errors={400: ('CreateObservabilityDestination400', CreateObservabilityDestination400), 401: ('CreateObservabilityDestination401', CreateObservabilityDestination401), 403: ('CreateObservabilityDestination403', CreateObservabilityDestination403), 409: ('CreateObservabilityDestination409', CreateObservabilityDestination409), 500: ('CreateObservabilityDestination500', CreateObservabilityDestination500)})
_GET_OBSERVABILITY_DESTINATION = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetObservabilityDestination200, errors={401: ('GetObservabilityDestination401', GetObservabilityDestination401), 404: ('GetObservabilityDestination404', GetObservabilityDestination404), 500: ('GetObservabilityDestination500', GetObservabilityDestination500)})
_DELETE_OBSERVABILITY_DESTINATION = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteObservabilityDestination200, errors={401: ('DeleteObservabilityDestination401', DeleteObservabilityDestination401), 404: ('DeleteObservabilityDestination404', DeleteObservabilityDestination404), 500: ('DeleteObservabilityDestination500', DeleteObservabilityDestination500)})
_UPDATE_OBSERVABILITY_DESTINATION = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateObservabilityDestination200, errors={400: ('UpdateObservabilityDestination400', UpdateObservabilityDestination400), 401: ('UpdateObservabilityDestination401', UpdateObservabilityDestination401), 404: ('UpdateObservabilityDestination404', UpdateObservabilityDestination404), 409: ('UpdateObservabilityDestination409', UpdateObservabilityDestination409), 500: ('UpdateObservabilityDestination500', UpdateObservabilityDestination500)})
_LIST_ORGANIZATION_MEMBERS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListOrganizationMembers200, errors={401: ('ListOrganizationMembers401', ListOrganizationMembers401), 404: ('ListOrganizationMembers404', ListOrganizationMembers404), 500: ('ListOrganizationMembers500', ListOrganizationMembers500)})
_LIST_PRESETS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListPresets200, errors={400: ('ListPresets400', ListPresets400), 401: ('ListPresets401', ListPresets401), 500: ('ListPresets500', ListPresets500)})
_GET_PRESET = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetPreset200, errors={400: ('GetPreset400', GetPreset400), 401: ('GetPreset401', GetPreset401), 404: ('GetPreset404', GetPreset404), 500: ('GetPreset500', GetPreset500)})
_CREATE_PRESETS_CHAT_COMPLETIONS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreatePresetsChatCompletions200, errors={400: ('CreatePresetsChatCompletions400', CreatePresetsChatCompletions400), 401: ('CreatePresetsChatCompletions401', CreatePresetsChatCompletions401), 403: ('CreatePresetsChatCompletions403', CreatePresetsChatCompletions403), 404: ('CreatePresetsChatCompletions404', CreatePresetsChatCompletions404), 409: ('CreatePresetsChatCompletions409', CreatePresetsChatCompletions409), 500: ('CreatePresetsChatCompletions500', CreatePresetsChatCompletions500)})
_CREATE_PRESETS_MESSAGES = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreatePresetsMessages200, errors={400: ('CreatePresetsMessages400', CreatePresetsMessages400), 401: ('CreatePresetsMessages401', CreatePresetsMessages401), 403: ('CreatePresetsMessages403', CreatePresetsMessages403), 404: ('CreatePresetsMessages404', CreatePresetsMessages404), 409: ('CreatePresetsMessages409', CreatePresetsMessages409), 500: ('CreatePresetsMessages500', CreatePresetsMessages500)})
_CREATE_PRESETS_RESPONSES = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreatePresetsResponses200, errors={400: ('CreatePresetsResponses400', CreatePresetsResponses400), 401: ('CreatePresetsResponses401', CreatePresetsResponses401), 403: ('CreatePresetsResponses403', CreatePresetsResponses403), 404: ('CreatePresetsResponses404', CreatePresetsResponses404), 409: ('CreatePresetsResponses409', CreatePresetsResponses409), 500: ('CreatePresetsResponses500', CreatePresetsResponses500)})
_LIST_PRESET_VERSIONS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListPresetVersions200, errors={400: ('ListPresetVersions400', ListPresetVersions400), 401: ('ListPresetVersions401', ListPresetVersions401), 404: ('ListPresetVersions404', ListPresetVersions404), 500: ('ListPresetVersions500', ListPresetVersions500)})
_GET_PRESET_VERSION = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetPresetVersion200, errors={400: ('GetPresetVersion400', GetPresetVersion400), 401: ('GetPresetVersion401', GetPresetVersion401), 404: ('GetPresetVersion404', GetPresetVersion404), 500: ('GetPresetVersion500', GetPresetVersion500)})
_LIST_PROVIDERS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListProviders200, errors={500: ('ListProviders500', ListProviders500)})
_CREATE_RERANK = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateRerank200, errors={400: ('CreateRerank400', CreateRerank400), 401: ('CreateRerank401', CreateRerank401), 402: ('CreateRerank402', CreateRerank402), 404: ('CreateRerank404', CreateRerank404), 429: ('CreateRerank429', CreateRerank429), 500: ('CreateRerank500', CreateRerank500), 502: ('CreateRerank502', CreateRerank502), 503: ('CreateRerank503', CreateRerank503), 524: ('CreateRerank524', CreateRerank524), 529: ('CreateRerank529', CreateRerank529)})
_CREATE_RERANK_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_CREATE_RESPONSES = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ), success=CreateResponses200, errors={400: ('CreateResponses400', CreateResponses400), 401: ('CreateResponses401', CreateResponses401), 402: ('CreateResponses402', CreateResponses402), 403: ('CreateResponses403', CreateResponses403), 404: ('CreateResponses404', CreateResponses404), 408: ('CreateResponses408', CreateResponses408), 413: ('CreateResponses413', CreateResponses413), 422: ('CreateResponses422', CreateResponses422), 429: ('CreateResponses429', CreateResponses429), 500: ('CreateResponses500', CreateResponses500), 502: ('CreateResponses502', CreateResponses502), 503: ('CreateResponses503', CreateResponses503), 524: ('CreateResponses524', CreateResponses524), 529: ('CreateResponses529', CreateResponses529)})
_CREATE_RESPONSES_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ))
_CREATE_VIDEOS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateVideos202, errors={400: ('CreateVideos400', CreateVideos400), 401: ('CreateVideos401', CreateVideos401), 402: ('CreateVideos402', CreateVideos402), 404: ('CreateVideos404', CreateVideos404), 429: ('CreateVideos429', CreateVideos429), 500: ('CreateVideos500', CreateVideos500)})
_GET_VIDEOS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetVideos200, errors={401: ('GetVideos401', GetVideos401), 404: ('GetVideos404', GetVideos404), 500: ('GetVideos500', GetVideos500)})
_LIST_VIDEOS_CONTENT = _c.Operation("GET", url_params=('index', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), errors={400: ('ListVideosContent400', ListVideosContent400), 401: ('ListVideosContent401', ListVideosContent401), 404: ('ListVideosContent404', ListVideosContent404), 500: ('ListVideosContent500', ListVideosContent500), 502: ('ListVideosContent502', ListVideosContent502)})
_LIST_VIDEOS_MODELS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListVideosModels200, errors={400: ('ListVideosModels400', ListVideosModels400), 500: ('ListVideosModels500', ListVideosModels500)})
_LIST_WORKSPACES = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListWorkspaces200, errors={401: ('ListWorkspaces401', ListWorkspaces401), 500: ('ListWorkspaces500', ListWorkspaces500)})
_CREATE_WORKSPACE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateWorkspace201, errors={400: ('CreateWorkspace400', CreateWorkspace400), 401: ('CreateWorkspace401', CreateWorkspace401), 403: ('CreateWorkspace403', CreateWorkspace403), 500: ('CreateWorkspace500', CreateWorkspace500)})
_GET_WORKSPACE = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetWorkspace200, errors={401: ('GetWorkspace401', GetWorkspace401), 404: ('GetWorkspace404', GetWorkspace404), 500: ('GetWorkspace500', GetWorkspace500)})
_DELETE_WORKSPACE = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteWorkspace200, errors={400: ('DeleteWorkspace400', DeleteWorkspace400), 401: ('DeleteWorkspace401', DeleteWorkspace401), 403: ('DeleteWorkspace403', DeleteWorkspace403), 404: ('DeleteWorkspace404', DeleteWorkspace404), 500: ('DeleteWorkspace500', DeleteWorkspace500)})
_UPDATE_WORKSPACE = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateWorkspace200, errors={400: ('UpdateWorkspace400', UpdateWorkspace400), 401: ('UpdateWorkspace401', UpdateWorkspace401), 403: ('UpdateWorkspace403', UpdateWorkspace403), 404: ('UpdateWorkspace404', UpdateWorkspace404), 500: ('UpdateWorkspace500', UpdateWorkspace500)})
_LIST_WORKSPACE_BUDGETS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListWorkspaceBudgets200, errors={401: ('ListWorkspaceBudgets401', ListWorkspaceBudgets401), 404: ('ListWorkspaceBudgets404', ListWorkspaceBudgets404), 500: ('ListWorkspaceBudgets500', ListWorkspaceBudgets500)})
_UPSERT_WORKSPACE_BUDGET = _c.Operation("PUT", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpsertWorkspaceBudget200, errors={400: ('UpsertWorkspaceBudget400', UpsertWorkspaceBudget400), 401: ('UpsertWorkspaceBudget401', UpsertWorkspaceBudget401), 404: ('UpsertWorkspaceBudget404', UpsertWorkspaceBudget404), 500: ('UpsertWorkspaceBudget500', UpsertWorkspaceBudget500)})
_DELETE_WORKSPACE_BUDGET = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteWorkspaceBudget200, errors={401: ('DeleteWorkspaceBudget401', DeleteWorkspaceBudget401), 404: ('DeleteWorkspaceBudget404', DeleteWorkspaceBudget404), 500: ('DeleteWorkspaceBudget500', DeleteWorkspaceBudget500)})
_LIST_WORKSPACE_MEMBERS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListWorkspaceMembers200, errors={401: ('ListWorkspaceMembers401', ListWorkspaceMembers401), 403: ('ListWorkspaceMembers403', ListWorkspaceMembers403), 404: ('ListWorkspaceMembers404', ListWorkspaceMembers404), 500: ('ListWorkspaceMembers500', ListWorkspaceMembers500)})
_BULK_ADD_WORKSPACE_MEMBERS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkAddWorkspaceMembers200, errors={400: ('BulkAddWorkspaceMembers400', BulkAddWorkspaceMembers400), 401: ('BulkAddWorkspaceMembers401', BulkAddWorkspaceMembers401), 403: ('BulkAddWorkspaceMembers403', BulkAddWorkspaceMembers403), 404: ('BulkAddWorkspaceMembers404', BulkAddWorkspaceMembers404), 500: ('BulkAddWorkspaceMembers500', BulkAddWorkspaceMembers500)})
_BULK_REMOVE_WORKSPACE_MEMBERS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkRemoveWorkspaceMembers200, errors={400: ('BulkRemoveWorkspaceMembers400', BulkRemoveWorkspaceMembers400), 401: ('BulkRemoveWorkspaceMembers401', BulkRemoveWorkspaceMembers401), 403: ('BulkRemoveWorkspaceMembers403', BulkRemoveWorkspaceMembers403), 404: ('BulkRemoveWorkspaceMembers404', BulkRemoveWorkspaceMembers404), 500: ('BulkRemoveWorkspaceMembers500', BulkRemoveWorkspaceMembers500)})


class OpenRouterClient(_c.GeneratedClient):
    """The OpenRouter API: build it with ``make``."""

    __slots__ = ()

    error_class = OpenRouterClientError

    @_t.overload
    def get_user_activity(self, *, params: _T.GetUserActivityParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetUserActivity200, _Errors]: ...
    @_t.overload
    def get_user_activity(self, *, params: _T.GetUserActivityParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetUserActivity200, _HttpClientResponse], _Errors]: ...
    def get_user_activity(self, *, params: _T.GetUserActivityParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns user activity data grouped by endpoint for the last 30 (completed) UTC days. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_USER_ACTIVITY, "/activity", params, None, include_response)

    @_t.overload
    def get_analytics_meta(self, *, params: _T.GetAnalyticsMetaParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetAnalyticsMeta200, _Errors]: ...
    @_t.overload
    def get_analytics_meta(self, *, params: _T.GetAnalyticsMetaParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetAnalyticsMeta200, _HttpClientResponse], _Errors]: ...
    def get_analytics_meta(self, *, params: _T.GetAnalyticsMetaParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns the available metrics, dimensions, filter operators, and granularities for the analytics query endpoint. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_ANALYTICS_META, "/analytics/meta", params, None, include_response)

    @_t.overload
    def query_analytics(self, *, payload: _T.QueryAnalyticsRequestJson, params: _T.QueryAnalyticsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.QueryAnalytics200, _Errors]: ...
    @_t.overload
    def query_analytics(self, *, payload: _T.QueryAnalyticsRequestJson, params: _T.QueryAnalyticsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.QueryAnalytics200, _HttpClientResponse], _Errors]: ...
    def query_analytics(self, *, payload: _T.QueryAnalyticsRequestJson, params: _T.QueryAnalyticsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Execute an analytics query with specified metrics, dimensions, filters, and time range. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_QUERY_ANALYTICS, "/analytics/query", params, _c.json_body(payload), include_response)

    @_t.overload
    def create_audio_speech(self, *, payload: _T.CreateAudioSpeechRequestJson, params: _T.CreateAudioSpeechParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def create_audio_speech(self, *, payload: _T.CreateAudioSpeechRequestJson, params: _T.CreateAudioSpeechParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def create_audio_speech(self, *, payload: _T.CreateAudioSpeechRequestJson, params: _T.CreateAudioSpeechParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Synthesizes audio from the input text. Returns a raw audio bytestream in the requested format (e.g. mp3, pcm, wav)."""
        return self._json(_CREATE_AUDIO_SPEECH, "/audio/speech", params, _c.json_body(payload), include_response)

    @_t.overload
    def create_audio_transcriptions(self, *, payload: _T.CreateAudioTranscriptionsRequestJson, params: _T.CreateAudioTranscriptionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateAudioTranscriptions200, _Errors]: ...
    @_t.overload
    def create_audio_transcriptions(self, *, payload: _T.CreateAudioTranscriptionsRequestJson, params: _T.CreateAudioTranscriptionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateAudioTranscriptions200, _HttpClientResponse], _Errors]: ...
    def create_audio_transcriptions(self, *, payload: _T.CreateAudioTranscriptionsRequestJson, params: _T.CreateAudioTranscriptionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Transcribes audio into text. Accepts base64-encoded audio input as JSON or an OpenAI-style multipart/form-data file upload, and returns the transcribed text."""
        return self._json(_CREATE_AUDIO_TRANSCRIPTIONS, "/audio/transcriptions", params, _c.json_body(payload), include_response)

    @_t.overload
    def exchange_auth_code_for_api_key(self, *, payload: _T.ExchangeAuthCodeForAPIKeyRequestJson, params: _T.ExchangeAuthCodeForAPIKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ExchangeAuthCodeForAPIKey200, _Errors]: ...
    @_t.overload
    def exchange_auth_code_for_api_key(self, *, payload: _T.ExchangeAuthCodeForAPIKeyRequestJson, params: _T.ExchangeAuthCodeForAPIKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ExchangeAuthCodeForAPIKey200, _HttpClientResponse], _Errors]: ...
    def exchange_auth_code_for_api_key(self, *, payload: _T.ExchangeAuthCodeForAPIKeyRequestJson, params: _T.ExchangeAuthCodeForAPIKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Exchange an authorization code from the PKCE flow for a user-controlled API key"""
        return self._json(_EXCHANGE_AUTH_CODE_FOR_API_KEY, "/auth/keys", params, _c.json_body(payload), include_response)

    @_t.overload
    def create_auth_keys_code(self, *, payload: _T.CreateAuthKeysCodeRequestJson, params: _T.CreateAuthKeysCodeParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateAuthKeysCode200, _Errors]: ...
    @_t.overload
    def create_auth_keys_code(self, *, payload: _T.CreateAuthKeysCodeRequestJson, params: _T.CreateAuthKeysCodeParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateAuthKeysCode200, _HttpClientResponse], _Errors]: ...
    def create_auth_keys_code(self, *, payload: _T.CreateAuthKeysCodeRequestJson, params: _T.CreateAuthKeysCodeParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create an authorization code for the PKCE flow to generate a user-controlled API key"""
        return self._json(_CREATE_AUTH_KEYS_CODE, "/auth/keys/code", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_benchmarks(self, *, params: _T.GetBenchmarksParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetBenchmarks200, _Errors]: ...
    @_t.overload
    def get_benchmarks(self, *, params: _T.GetBenchmarksParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetBenchmarks200, _HttpClientResponse], _Errors]: ...
    def get_benchmarks(self, *, params: _T.GetBenchmarksParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Unified benchmark endpoint that aggregates scores from multiple benchmark sources (Artificial Analysis, Design Arena). Filter by source to reproduce the exact shapes from the legacy per-source endpoints, or use task_type to find models suited for specific workloads. Authenticate with any valid OpenRouter API key. Rate-limited to 30 requests/minute per key and 500 requests/day per account."""
        return self._json(_GET_BENCHMARKS, "/benchmarks", params, None, include_response)

    @_t.overload
    def list_byok_keys(self, *, params: _T.ListBYOKKeysParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListBYOKKeys200, _Errors]: ...
    @_t.overload
    def list_byok_keys(self, *, params: _T.ListBYOKKeysParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListBYOKKeys200, _HttpClientResponse], _Errors]: ...
    def list_byok_keys(self, *, params: _T.ListBYOKKeysParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the bring-your-own-key (BYOK) provider credentials for the authenticated entity's default workspace. Use the `workspace_id` query parameter to scope the result to a different workspace, or the `provider` query parameter to filter by upstream provider. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_BYOK_KEYS, "/byok", params, None, include_response)

    @_t.overload
    def create_byok_key(self, *, payload: _T.CreateBYOKKeyRequestJson, params: _T.CreateBYOKKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateBYOKKey201, _Errors]: ...
    @_t.overload
    def create_byok_key(self, *, payload: _T.CreateBYOKKeyRequestJson, params: _T.CreateBYOKKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateBYOKKey201, _HttpClientResponse], _Errors]: ...
    def create_byok_key(self, *, payload: _T.CreateBYOKKeyRequestJson, params: _T.CreateBYOKKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new bring-your-own-key (BYOK) provider credential. The raw key is encrypted at rest and never returned in API responses. Defaults to the authenticated entity's default workspace; use the `workspace_id` body field to scope to a different workspace. Treat the raw key as write-only; it is never returned after creation. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_BYOK_KEY, "/byok", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_byok_key(self, id: str, *, params: _T.GetBYOKKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetBYOKKey200, _Errors]: ...
    @_t.overload
    def get_byok_key(self, id: str, *, params: _T.GetBYOKKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetBYOKKey200, _HttpClientResponse], _Errors]: ...
    def get_byok_key(self, id: str, *, params: _T.GetBYOKKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a single bring-your-own-key (BYOK) provider credential by its `id`. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_BYOK_KEY, f"/byok/{id}", params, None, include_response)

    @_t.overload
    def delete_byok_key(self, id: str, *, params: _T.DeleteBYOKKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteBYOKKey200, _Errors]: ...
    @_t.overload
    def delete_byok_key(self, id: str, *, params: _T.DeleteBYOKKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteBYOKKey200, _HttpClientResponse], _Errors]: ...
    def delete_byok_key(self, id: str, *, params: _T.DeleteBYOKKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete (soft-delete) a bring-your-own-key (BYOK) provider credential by its `id`. The encrypted key material is wiped and the record is marked as deleted. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_BYOK_KEY, f"/byok/{id}", params, None, include_response)

    @_t.overload
    def update_byok_key(self, id: str, *, payload: _T.UpdateBYOKKeyRequestJson, params: _T.UpdateBYOKKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateBYOKKey200, _Errors]: ...
    @_t.overload
    def update_byok_key(self, id: str, *, payload: _T.UpdateBYOKKeyRequestJson, params: _T.UpdateBYOKKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateBYOKKey200, _HttpClientResponse], _Errors]: ...
    def update_byok_key(self, id: str, *, payload: _T.UpdateBYOKKeyRequestJson, params: _T.UpdateBYOKKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update an existing bring-your-own-key (BYOK) provider credential by its `id`. Include the `key` field to rotate the raw provider API key in-place (the previous key material is overwritten). [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_BYOK_KEY, f"/byok/{id}", params, _c.json_body(payload), include_response)

    @_t.overload
    def send_chat_completion_request(self, *, payload: _T.SendChatCompletionRequestRequestJson, params: _T.SendChatCompletionRequestParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.SendChatCompletionRequest200, _Errors]: ...
    @_t.overload
    def send_chat_completion_request(self, *, payload: _T.SendChatCompletionRequestRequestJson, params: _T.SendChatCompletionRequestParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.SendChatCompletionRequest200, _HttpClientResponse], _Errors]: ...
    def send_chat_completion_request(self, *, payload: _T.SendChatCompletionRequestRequestJson, params: _T.SendChatCompletionRequestParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Sends a request for a model response for the given chat conversation. Supports both streaming and non-streaming modes."""
        return self._json(_SEND_CHAT_COMPLETION_REQUEST, "/chat/completions", params, _c.json_body(payload), include_response)

    def send_chat_completion_request_sse(self, *, payload: _T.SendChatCompletionRequestRequestJson, params: _T.SendChatCompletionRequestParams | None = None) -> _Stream[_sse.DataEvent[_T.SendChatCompletionRequest200Sse], _SseErrors]:
        """Sends a request for a model response for the given chat conversation. Supports both streaming and non-streaming modes."""
        return self._sse(_SEND_CHAT_COMPLETION_REQUEST_SSE, "/chat/completions", params, _c.json_body(payload), SendChatCompletionRequest200Sse)

    @_t.overload
    def get_task_classifications(self, *, params: _T.GetTaskClassificationsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetTaskClassifications200, _Errors]: ...
    @_t.overload
    def get_task_classifications(self, *, params: _T.GetTaskClassificationsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetTaskClassifications200, _HttpClientResponse], _Errors]: ...
    def get_task_classifications(self, *, params: _T.GetTaskClassificationsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns the market-share breakdown of OpenRouter traffic by task classification
        (e.g. code generation, web search, summarization) over a trailing time window.
        
        Each classification reports its share of classified sampled requests (`usage_share`)
        and classified sampled token volume (`token_share`) as fractions between 0 and 1.
        The unclassified `other` bucket is excluded. Absolute volumes are not exposed
        because the underlying data is sampled.
        
        Each classification also includes a `models` array listing the top models by
        request volume within that classification, with their within-tag usage and token shares.
        
        Classifications are grouped into macro-categories (Code, Data, Agent, General)
        with aggregate shares provided for each.
        
        Authenticate with any valid OpenRouter API key (same key used for inference).
        Rate-limited to 30 requests/minute per key and 500 requests/day per account.
        
        When republishing or quoting this data, cite as:
        "Source: OpenRouter (openrouter.ai/rankings), as of {as_of}." """
        return self._json(_GET_TASK_CLASSIFICATIONS, "/classifications/task", params, None, include_response)

    @_t.overload
    def get_credits(self, *, params: _T.GetCreditsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetCredits200, _Errors]: ...
    @_t.overload
    def get_credits(self, *, params: _T.GetCreditsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetCredits200, _HttpClientResponse], _Errors]: ...
    def get_credits(self, *, params: _T.GetCreditsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get total credits purchased and used for the authenticated user. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_CREDITS, "/credits", params, None, include_response)

    @_t.overload
    def create_coinbase_charge(self, *, params: _T.CreateCoinbaseChargeParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def create_coinbase_charge(self, *, params: _T.CreateCoinbaseChargeParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def create_coinbase_charge(self, *, params: _T.CreateCoinbaseChargeParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deprecated. The Coinbase APIs used by this endpoint have been deprecated, so Coinbase Commerce charges have been removed. Use the web credits purchase flow instead."""
        return self._json(_CREATE_COINBASE_CHARGE, "/credits/coinbase", params, None, include_response)

    @_t.overload
    def get_app_rankings(self, *, params: _T.GetAppRankingsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetAppRankings200, _Errors]: ...
    @_t.overload
    def get_app_rankings(self, *, params: _T.GetAppRankingsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetAppRankings200, _HttpClientResponse], _Errors]: ...
    def get_app_rankings(self, *, params: _T.GetAppRankingsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns the top public apps on OpenRouter ranked by token usage inside the requested
        date window, matching the public apps marketplace on openrouter.ai/apps. Token totals
        are `prompt_tokens + completion_tokens`; hidden and private apps are excluded and
        traffic from related app aliases is merged into the canonical visible app.
        
        `sort=popular` (default) ranks by total token volume inside the window.
        `sort=trending` ranks by absolute excess token growth: window volume minus the average
        volume of the three equal-length periods immediately preceding the window. Apps with
        no excess growth are omitted, so `trending` may return fewer than `limit` rows.
        
        Filter with `category` (marketplace category group, e.g. `coding`) or `subcategory`
        (e.g. `cli-agent`). Ranks are re-numbered 1..N after filtering. Page with `offset` —
        `rank` stays absolute, so the first row of `offset=50` is `rank: 51`.
        
        Authenticate with any valid OpenRouter API key (same key used for inference).
        Rate-limited to 30 requests/minute per key and 500 requests/day per account.
        
        When republishing or quoting this dataset, OpenRouter must be cited as:
        "Source: OpenRouter (openrouter.ai/apps), as of {as_of}."
        
        Token counts come from each upstream provider's own tokenizer, so a token attributed
        to one app is not directly comparable to a token attributed to another app whose
        traffic flows through a different provider."""
        return self._json(_GET_APP_RANKINGS, "/datasets/app-rankings", params, None, include_response)

    @_t.overload
    def get_rankings_daily(self, *, params: _T.GetRankingsDailyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetRankingsDaily200, _Errors]: ...
    @_t.overload
    def get_rankings_daily(self, *, params: _T.GetRankingsDailyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetRankingsDaily200, _HttpClientResponse], _Errors]: ...
    def get_rankings_daily(self, *, params: _T.GetRankingsDailyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns the top 50 public models per day by total token usage on OpenRouter, plus a
        single aggregated `other` row per day that sums every model outside that top 50.
        Token totals are `prompt_tokens + completion_tokens`, matching the public rankings
        chart on openrouter.ai/rankings.
        
        Each row is a distinct `(date, model_permaslug)` pair. The `other` row uses the
        reserved permaslug `other` and is always returned last within its date, so callers
        can compute `top-50 traffic / total daily traffic` without a second request.
        
        Optional filters slice the dataset. `period` (`day`/`week`/`month`) sets the time
        grain. `modality` and `context_bucket` narrow the exact dataset by output/input
        modality (or tool-calling activity) and request context length. `category` and
        `language_type` instead read a sampled, upsampled dataset whose `total_tokens` are
        weekly-grain estimates — they cannot be combined with each other or with the exact
        filters, and reject `period=day` with a 400.
        
        Authenticate with any valid OpenRouter API key (same key used for inference).
        Rate-limited to 30 requests/minute per key and 500 requests/day per account.
        
        When republishing or quoting this dataset, OpenRouter must be cited as:
        "Source: OpenRouter (openrouter.ai/rankings), as of {as_of}."
        
        Token counts come from each upstream provider's own tokenizer (Anthropic counts
        are as reported by Anthropic, OpenAI counts are as reported by OpenAI, etc.), so
        a token in one row is not directly comparable to a token in another row from a
        different provider."""
        return self._json(_GET_RANKINGS_DAILY, "/datasets/rankings-daily", params, None, include_response)

    @_t.overload
    def create_embeddings(self, *, payload: _T.CreateEmbeddingsRequestJson, params: _T.CreateEmbeddingsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateEmbeddings200, _Errors]: ...
    @_t.overload
    def create_embeddings(self, *, payload: _T.CreateEmbeddingsRequestJson, params: _T.CreateEmbeddingsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateEmbeddings200, _HttpClientResponse], _Errors]: ...
    def create_embeddings(self, *, payload: _T.CreateEmbeddingsRequestJson, params: _T.CreateEmbeddingsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Submits an embedding request to the embeddings router"""
        return self._json(_CREATE_EMBEDDINGS, "/embeddings", params, _c.json_body(payload), include_response)

    def create_embeddings_sse(self, *, payload: _T.CreateEmbeddingsRequestJson, params: _T.CreateEmbeddingsParams | None = None) -> _Stream[_sse.DataEvent[_T.CreateEmbeddings200Sse], _SseErrors]:
        """Submits an embedding request to the embeddings router"""
        return self._sse(_CREATE_EMBEDDINGS_SSE, "/embeddings", params, _c.json_body(payload), CreateEmbeddings200Sse)

    @_t.overload
    def list_embeddings_models(self, *, params: _T.ListEmbeddingsModelsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListEmbeddingsModels200, _Errors]: ...
    @_t.overload
    def list_embeddings_models(self, *, params: _T.ListEmbeddingsModelsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListEmbeddingsModels200, _HttpClientResponse], _Errors]: ...
    def list_embeddings_models(self, *, params: _T.ListEmbeddingsModelsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of all available embeddings models and their properties"""
        return self._json(_LIST_EMBEDDINGS_MODELS, "/embeddings/models", params, None, include_response)

    @_t.overload
    def list_endpoints_zdr(self, *, params: _T.ListEndpointsZdrParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListEndpointsZdr200, _Errors]: ...
    @_t.overload
    def list_endpoints_zdr(self, *, params: _T.ListEndpointsZdrParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListEndpointsZdr200, _HttpClientResponse], _Errors]: ...
    def list_endpoints_zdr(self, *, params: _T.ListEndpointsZdrParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Preview the impact of ZDR on the available endpoints"""
        return self._json(_LIST_ENDPOINTS_ZDR, "/endpoints/zdr", params, None, include_response)

    @_t.overload
    def list_files(self, *, params: _T.ListFilesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListFiles200, _Errors]: ...
    @_t.overload
    def list_files(self, *, params: _T.ListFilesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListFiles200, _HttpClientResponse], _Errors]: ...
    def list_files(self, *, params: _T.ListFilesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists files belonging to the workspace of the authenticating API key."""
        return self._json(_LIST_FILES, "/files", params, None, include_response)

    @_t.overload
    def upload_file(self, *, payload: _T.UploadFileRequestFormData, params: _T.UploadFileParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UploadFile200, _Errors]: ...
    @_t.overload
    def upload_file(self, *, payload: _T.UploadFileRequestFormData, params: _T.UploadFileParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UploadFile200, _HttpClientResponse], _Errors]: ...
    def upload_file(self, *, payload: _T.UploadFileRequestFormData, params: _T.UploadFileParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Uploads a file to be referenced in future API calls. The file is stored under the workspace of the authenticating API key. Maximum file size: 100 MB."""
        return self._json(_UPLOAD_FILE, "/files", params, _c.form_body(payload), include_response)

    @_t.overload
    def get_file_metadata(self, file_id: str, *, params: _T.GetFileMetadataParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetFileMetadata200, _Errors]: ...
    @_t.overload
    def get_file_metadata(self, file_id: str, *, params: _T.GetFileMetadataParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetFileMetadata200, _HttpClientResponse], _Errors]: ...
    def get_file_metadata(self, file_id: str, *, params: _T.GetFileMetadataParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves metadata for a single file owned by the requesting workspace."""
        return self._json(_GET_FILE_METADATA, f"/files/{file_id}", params, None, include_response)

    @_t.overload
    def delete_file(self, file_id: str, *, params: _T.DeleteFileParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteFile200, _Errors]: ...
    @_t.overload
    def delete_file(self, file_id: str, *, params: _T.DeleteFileParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteFile200, _HttpClientResponse], _Errors]: ...
    def delete_file(self, file_id: str, *, params: _T.DeleteFileParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a file owned by the requesting workspace. Deletion is irreversible."""
        return self._json(_DELETE_FILE, f"/files/{file_id}", params, None, include_response)

    @_t.overload
    def download_file_content(self, file_id: str, *, params: _T.DownloadFileContentParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def download_file_content(self, file_id: str, *, params: _T.DownloadFileContentParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def download_file_content(self, file_id: str, *, params: _T.DownloadFileContentParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Downloads the raw bytes of a file. Only files created server-side are downloadable; uploaded files return 400."""
        return self._json(_DOWNLOAD_FILE_CONTENT, f"/files/{file_id}/content", params, None, include_response)

    def download_file_content_stream(self, file_id: str, *, params: _T.DownloadFileContentParams | None = None) -> _Stream[bytes, _HttpClientError]:
        """Downloads the raw bytes of a file. Only files created server-side are downloadable; uploaded files return 400."""
        return self._binary(_DOWNLOAD_FILE_CONTENT_STREAM, f"/files/{file_id}/content", params, None)

    @_t.overload
    def get_generation(self, *, params: _T.GetGenerationParams, include_response: _t.Literal[False] = False) -> _Effect[_T.GetGeneration200, _Errors]: ...
    @_t.overload
    def get_generation(self, *, params: _T.GetGenerationParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetGeneration200, _HttpClientResponse], _Errors]: ...
    def get_generation(self, *, params: _T.GetGenerationParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get request & usage metadata for a generation"""
        return self._json(_GET_GENERATION, "/generation", params, None, include_response)

    @_t.overload
    def list_generation_content(self, *, params: _T.ListGenerationContentParams, include_response: _t.Literal[False] = False) -> _Effect[_T.ListGenerationContent200, _Errors]: ...
    @_t.overload
    def list_generation_content(self, *, params: _T.ListGenerationContentParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListGenerationContent200, _HttpClientResponse], _Errors]: ...
    def list_generation_content(self, *, params: _T.ListGenerationContentParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get stored prompt and completion content for a generation"""
        return self._json(_LIST_GENERATION_CONTENT, "/generation/content", params, None, include_response)

    @_t.overload
    def submit_generation_feedback(self, *, payload: _T.SubmitGenerationFeedbackRequestJson, params: _T.SubmitGenerationFeedbackParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.SubmitGenerationFeedback200, _Errors]: ...
    @_t.overload
    def submit_generation_feedback(self, *, payload: _T.SubmitGenerationFeedbackRequestJson, params: _T.SubmitGenerationFeedbackParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.SubmitGenerationFeedback200, _HttpClientResponse], _Errors]: ...
    def submit_generation_feedback(self, *, payload: _T.SubmitGenerationFeedbackRequestJson, params: _T.SubmitGenerationFeedbackParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Submit structured feedback on a generation the authenticated user made. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_SUBMIT_GENERATION_FEEDBACK, "/generation/feedback", params, _c.json_body(payload), include_response)

    @_t.overload
    def list_guardrails(self, *, params: _T.ListGuardrailsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListGuardrails200, _Errors]: ...
    @_t.overload
    def list_guardrails(self, *, params: _T.ListGuardrailsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListGuardrails200, _HttpClientResponse], _Errors]: ...
    def list_guardrails(self, *, params: _T.ListGuardrailsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all guardrails for the authenticated user. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_GUARDRAILS, "/guardrails", params, None, include_response)

    @_t.overload
    def create_guardrail(self, *, payload: _T.CreateGuardrailRequestJson, params: _T.CreateGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateGuardrail201, _Errors]: ...
    @_t.overload
    def create_guardrail(self, *, payload: _T.CreateGuardrailRequestJson, params: _T.CreateGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateGuardrail201, _HttpClientResponse], _Errors]: ...
    def create_guardrail(self, *, payload: _T.CreateGuardrailRequestJson, params: _T.CreateGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new guardrail for the authenticated user. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_GUARDRAIL, "/guardrails", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_guardrail(self, id: str, *, params: _T.GetGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetGuardrail200, _Errors]: ...
    @_t.overload
    def get_guardrail(self, id: str, *, params: _T.GetGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetGuardrail200, _HttpClientResponse], _Errors]: ...
    def get_guardrail(self, id: str, *, params: _T.GetGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a single guardrail by ID. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_GUARDRAIL, f"/guardrails/{id}", params, None, include_response)

    @_t.overload
    def delete_guardrail(self, id: str, *, params: _T.DeleteGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteGuardrail200, _Errors]: ...
    @_t.overload
    def delete_guardrail(self, id: str, *, params: _T.DeleteGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteGuardrail200, _HttpClientResponse], _Errors]: ...
    def delete_guardrail(self, id: str, *, params: _T.DeleteGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an existing guardrail. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_GUARDRAIL, f"/guardrails/{id}", params, None, include_response)

    @_t.overload
    def update_guardrail(self, id: str, *, payload: _T.UpdateGuardrailRequestJson, params: _T.UpdateGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateGuardrail200, _Errors]: ...
    @_t.overload
    def update_guardrail(self, id: str, *, payload: _T.UpdateGuardrailRequestJson, params: _T.UpdateGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateGuardrail200, _HttpClientResponse], _Errors]: ...
    def update_guardrail(self, id: str, *, payload: _T.UpdateGuardrailRequestJson, params: _T.UpdateGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update an existing guardrail. Collection fields use replace semantics: send the full desired set on every update. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_GUARDRAIL, f"/guardrails/{id}", params, _c.json_body(payload), include_response)

    @_t.overload
    def list_guardrail_key_assignments(self, id: str, *, params: _T.ListGuardrailKeyAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListGuardrailKeyAssignments200, _Errors]: ...
    @_t.overload
    def list_guardrail_key_assignments(self, id: str, *, params: _T.ListGuardrailKeyAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListGuardrailKeyAssignments200, _HttpClientResponse], _Errors]: ...
    def list_guardrail_key_assignments(self, id: str, *, params: _T.ListGuardrailKeyAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all API key assignments for a specific guardrail. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_GUARDRAIL_KEY_ASSIGNMENTS, f"/guardrails/{id}/assignments/keys", params, None, include_response)

    @_t.overload
    def bulk_assign_keys_to_guardrail(self, id: str, *, payload: _T.BulkAssignKeysToGuardrailRequestJson, params: _T.BulkAssignKeysToGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkAssignKeysToGuardrail200, _Errors]: ...
    @_t.overload
    def bulk_assign_keys_to_guardrail(self, id: str, *, payload: _T.BulkAssignKeysToGuardrailRequestJson, params: _T.BulkAssignKeysToGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkAssignKeysToGuardrail200, _HttpClientResponse], _Errors]: ...
    def bulk_assign_keys_to_guardrail(self, id: str, *, payload: _T.BulkAssignKeysToGuardrailRequestJson, params: _T.BulkAssignKeysToGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Assign multiple API keys to a specific guardrail. A key may hold at most one guardrail; assigning replaces any existing assignment. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_ASSIGN_KEYS_TO_GUARDRAIL, f"/guardrails/{id}/assignments/keys", params, _c.json_body(payload), include_response)

    @_t.overload
    def bulk_unassign_keys_from_guardrail(self, id: str, *, payload: _T.BulkUnassignKeysFromGuardrailRequestJson, params: _T.BulkUnassignKeysFromGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkUnassignKeysFromGuardrail200, _Errors]: ...
    @_t.overload
    def bulk_unassign_keys_from_guardrail(self, id: str, *, payload: _T.BulkUnassignKeysFromGuardrailRequestJson, params: _T.BulkUnassignKeysFromGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkUnassignKeysFromGuardrail200, _HttpClientResponse], _Errors]: ...
    def bulk_unassign_keys_from_guardrail(self, id: str, *, payload: _T.BulkUnassignKeysFromGuardrailRequestJson, params: _T.BulkUnassignKeysFromGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Unassign multiple API keys from a specific guardrail. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_UNASSIGN_KEYS_FROM_GUARDRAIL, f"/guardrails/{id}/assignments/keys/remove", params, _c.json_body(payload), include_response)

    @_t.overload
    def list_guardrail_member_assignments(self, id: str, *, params: _T.ListGuardrailMemberAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListGuardrailMemberAssignments200, _Errors]: ...
    @_t.overload
    def list_guardrail_member_assignments(self, id: str, *, params: _T.ListGuardrailMemberAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListGuardrailMemberAssignments200, _HttpClientResponse], _Errors]: ...
    def list_guardrail_member_assignments(self, id: str, *, params: _T.ListGuardrailMemberAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all organization member assignments for a specific guardrail. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_GUARDRAIL_MEMBER_ASSIGNMENTS, f"/guardrails/{id}/assignments/members", params, None, include_response)

    @_t.overload
    def bulk_assign_members_to_guardrail(self, id: str, *, payload: _T.BulkAssignMembersToGuardrailRequestJson, params: _T.BulkAssignMembersToGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkAssignMembersToGuardrail200, _Errors]: ...
    @_t.overload
    def bulk_assign_members_to_guardrail(self, id: str, *, payload: _T.BulkAssignMembersToGuardrailRequestJson, params: _T.BulkAssignMembersToGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkAssignMembersToGuardrail200, _HttpClientResponse], _Errors]: ...
    def bulk_assign_members_to_guardrail(self, id: str, *, payload: _T.BulkAssignMembersToGuardrailRequestJson, params: _T.BulkAssignMembersToGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Assign multiple organization members to a specific guardrail. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_ASSIGN_MEMBERS_TO_GUARDRAIL, f"/guardrails/{id}/assignments/members", params, _c.json_body(payload), include_response)

    @_t.overload
    def bulk_unassign_members_from_guardrail(self, id: str, *, payload: _T.BulkUnassignMembersFromGuardrailRequestJson, params: _T.BulkUnassignMembersFromGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkUnassignMembersFromGuardrail200, _Errors]: ...
    @_t.overload
    def bulk_unassign_members_from_guardrail(self, id: str, *, payload: _T.BulkUnassignMembersFromGuardrailRequestJson, params: _T.BulkUnassignMembersFromGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkUnassignMembersFromGuardrail200, _HttpClientResponse], _Errors]: ...
    def bulk_unassign_members_from_guardrail(self, id: str, *, payload: _T.BulkUnassignMembersFromGuardrailRequestJson, params: _T.BulkUnassignMembersFromGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Unassign multiple organization members from a specific guardrail. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_UNASSIGN_MEMBERS_FROM_GUARDRAIL, f"/guardrails/{id}/assignments/members/remove", params, _c.json_body(payload), include_response)

    @_t.overload
    def list_key_assignments(self, *, params: _T.ListKeyAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListKeyAssignments200, _Errors]: ...
    @_t.overload
    def list_key_assignments(self, *, params: _T.ListKeyAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListKeyAssignments200, _HttpClientResponse], _Errors]: ...
    def list_key_assignments(self, *, params: _T.ListKeyAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all API key guardrail assignments for the authenticated user. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_KEY_ASSIGNMENTS, "/guardrails/assignments/keys", params, None, include_response)

    @_t.overload
    def list_member_assignments(self, *, params: _T.ListMemberAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListMemberAssignments200, _Errors]: ...
    @_t.overload
    def list_member_assignments(self, *, params: _T.ListMemberAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListMemberAssignments200, _HttpClientResponse], _Errors]: ...
    def list_member_assignments(self, *, params: _T.ListMemberAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all organization member guardrail assignments for the authenticated user. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_MEMBER_ASSIGNMENTS, "/guardrails/assignments/members", params, None, include_response)

    @_t.overload
    def create_images(self, *, payload: _T.CreateImagesRequestJson, params: _T.CreateImagesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateImages200, _Errors]: ...
    @_t.overload
    def create_images(self, *, payload: _T.CreateImagesRequestJson, params: _T.CreateImagesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateImages200, _HttpClientResponse], _Errors]: ...
    def create_images(self, *, payload: _T.CreateImagesRequestJson, params: _T.CreateImagesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Generates an image from a text prompt via the image generation router"""
        return self._json(_CREATE_IMAGES, "/images", params, _c.json_body(payload), include_response)

    def create_images_sse(self, *, payload: _T.CreateImagesRequestJson, params: _T.CreateImagesParams | None = None) -> _Stream[_sse.DataEvent[_T.CreateImages200Sse], _SseErrors]:
        """Generates an image from a text prompt via the image generation router"""
        return self._sse(_CREATE_IMAGES_SSE, "/images", params, _c.json_body(payload), CreateImages200Sse)

    @_t.overload
    def list_image_models(self, *, params: _T.ListImageModelsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListImageModels200, _Errors]: ...
    @_t.overload
    def list_image_models(self, *, params: _T.ListImageModelsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListImageModels200, _HttpClientResponse], _Errors]: ...
    def list_image_models(self, *, params: _T.ListImageModelsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists every image generation model with its top-level supported-parameter superset and a URL to its full per-endpoint records."""
        return self._json(_LIST_IMAGE_MODELS, "/images/models", params, None, include_response)

    @_t.overload
    def list_image_model_endpoints(self, author: str, slug: str, *, params: _T.ListImageModelEndpointsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListImageModelEndpoints200, _Errors]: ...
    @_t.overload
    def list_image_model_endpoints(self, author: str, slug: str, *, params: _T.ListImageModelEndpointsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListImageModelEndpoints200, _HttpClientResponse], _Errors]: ...
    def list_image_model_endpoints(self, author: str, slug: str, *, params: _T.ListImageModelEndpointsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns the full per-endpoint records for an image model: each endpoint's definitive supported parameters, pricing, and passthrough allowlist."""
        return self._json(_LIST_IMAGE_MODEL_ENDPOINTS, f"/images/models/{author}/{slug}/endpoints", params, None, include_response)

    @_t.overload
    def get_current_key(self, *, params: _T.GetCurrentKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetCurrentKey200, _Errors]: ...
    @_t.overload
    def get_current_key(self, *, params: _T.GetCurrentKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetCurrentKey200, _HttpClientResponse], _Errors]: ...
    def get_current_key(self, *, params: _T.GetCurrentKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get information on the API key associated with the current authentication session"""
        return self._json(_GET_CURRENT_KEY, "/key", params, None, include_response)

    @_t.overload
    def list(self, *, params: _T.ListParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.List200, _Errors]: ...
    @_t.overload
    def list(self, *, params: _T.ListParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.List200, _HttpClientResponse], _Errors]: ...
    def list(self, *, params: _T.ListParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all API keys for the authenticated user. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST, "/keys", params, None, include_response)

    @_t.overload
    def create_keys(self, *, payload: _T.CreateKeysRequestJson, params: _T.CreateKeysParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateKeys201, _Errors]: ...
    @_t.overload
    def create_keys(self, *, payload: _T.CreateKeysRequestJson, params: _T.CreateKeysParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateKeys201, _HttpClientResponse], _Errors]: ...
    def create_keys(self, *, payload: _T.CreateKeysRequestJson, params: _T.CreateKeysParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new API key for the authenticated user. The plaintext `key` is returned only in this response. Treat it as a write-only, sensitive value; it cannot be retrieved later. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_KEYS, "/keys", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_key(self, hash: str, *, params: _T.GetKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetKey200, _Errors]: ...
    @_t.overload
    def get_key(self, hash: str, *, params: _T.GetKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetKey200, _HttpClientResponse], _Errors]: ...
    def get_key(self, hash: str, *, params: _T.GetKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a single API key by hash. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_KEY, f"/keys/{hash}", params, None, include_response)

    @_t.overload
    def delete_keys(self, hash: str, *, params: _T.DeleteKeysParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteKeys200, _Errors]: ...
    @_t.overload
    def delete_keys(self, hash: str, *, params: _T.DeleteKeysParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteKeys200, _HttpClientResponse], _Errors]: ...
    def delete_keys(self, hash: str, *, params: _T.DeleteKeysParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an existing API key. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_KEYS, f"/keys/{hash}", params, None, include_response)

    @_t.overload
    def update_keys(self, hash: str, *, payload: _T.UpdateKeysRequestJson, params: _T.UpdateKeysParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateKeys200, _Errors]: ...
    @_t.overload
    def update_keys(self, hash: str, *, payload: _T.UpdateKeysRequestJson, params: _T.UpdateKeysParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateKeys200, _HttpClientResponse], _Errors]: ...
    def update_keys(self, hash: str, *, payload: _T.UpdateKeysRequestJson, params: _T.UpdateKeysParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update an existing API key. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_KEYS, f"/keys/{hash}", params, _c.json_body(payload), include_response)

    @_t.overload
    def create_messages(self, *, payload: _T.CreateMessagesRequestJson, params: _T.CreateMessagesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateMessages200, _Errors]: ...
    @_t.overload
    def create_messages(self, *, payload: _T.CreateMessagesRequestJson, params: _T.CreateMessagesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateMessages200, _HttpClientResponse], _Errors]: ...
    def create_messages(self, *, payload: _T.CreateMessagesRequestJson, params: _T.CreateMessagesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a message using the Anthropic Messages API format. Supports text, images, PDFs, tools, and extended thinking."""
        return self._json(_CREATE_MESSAGES, "/messages", params, _c.json_body(payload), include_response)

    def create_messages_sse(self, *, payload: _T.CreateMessagesRequestJson, params: _T.CreateMessagesParams | None = None) -> _Stream[_sse.DataEvent[_T.CreateMessages200Sse], _SseErrors]:
        """Creates a message using the Anthropic Messages API format. Supports text, images, PDFs, tools, and extended thinking."""
        return self._sse(_CREATE_MESSAGES_SSE, "/messages", params, _c.json_body(payload), CreateMessages200Sse)

    @_t.overload
    def get_model(self, author: str, slug: str, *, params: _T.GetModelParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetModel200, _Errors]: ...
    @_t.overload
    def get_model(self, author: str, slug: str, *, params: _T.GetModelParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetModel200, _HttpClientResponse], _Errors]: ...
    def get_model(self, author: str, slug: str, *, params: _T.GetModelParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns full details for a single model identified by its author and slug (e.g. openai/gpt-4). Supports variant suffixes (e.g. openai/gpt-4:free) and resolves known slug aliases."""
        return self._json(_GET_MODEL, f"/model/{author}/{slug}", params, None, include_response)

    @_t.overload
    def get_models(self, *, params: _T.GetModelsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetModels200, _Errors]: ...
    @_t.overload
    def get_models(self, *, params: _T.GetModelsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetModels200, _HttpClientResponse], _Errors]: ...
    def get_models(self, *, params: _T.GetModelsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all models and their properties"""
        return self._json(_GET_MODELS, "/models", params, None, include_response)

    @_t.overload
    def list_endpoints(self, author: str, slug: str, *, params: _T.ListEndpointsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListEndpoints200, _Errors]: ...
    @_t.overload
    def list_endpoints(self, author: str, slug: str, *, params: _T.ListEndpointsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListEndpoints200, _HttpClientResponse], _Errors]: ...
    def list_endpoints(self, author: str, slug: str, *, params: _T.ListEndpointsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all endpoints for a model"""
        return self._json(_LIST_ENDPOINTS, f"/models/{author}/{slug}/endpoints", params, None, include_response)

    @_t.overload
    def list_models_count(self, *, params: _T.ListModelsCountParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListModelsCount200, _Errors]: ...
    @_t.overload
    def list_models_count(self, *, params: _T.ListModelsCountParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListModelsCount200, _HttpClientResponse], _Errors]: ...
    def list_models_count(self, *, params: _T.ListModelsCountParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get total count of available models"""
        return self._json(_LIST_MODELS_COUNT, "/models/count", params, None, include_response)

    @_t.overload
    def list_models_user(self, *, params: _T.ListModelsUserParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListModelsUser200, _Errors]: ...
    @_t.overload
    def list_models_user(self, *, params: _T.ListModelsUserParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListModelsUser200, _HttpClientResponse], _Errors]: ...
    def list_models_user(self, *, params: _T.ListModelsUserParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List models filtered by user provider preferences, [privacy settings](https://openrouter.ai/docs/guides/privacy/provider-logging), and [guardrails](https://openrouter.ai/docs/guides/features/guardrails). If requesting through `eu.openrouter.ai/api/v1/...` the results will be filtered to models that satisfy [EU in-region routing](https://openrouter.ai/docs/guides/privacy/provider-logging#enterprise-eu-in-region-routing)."""
        return self._json(_LIST_MODELS_USER, "/models/user", params, None, include_response)

    @_t.overload
    def list_observability_destinations(self, *, params: _T.ListObservabilityDestinationsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListObservabilityDestinations200, _Errors]: ...
    @_t.overload
    def list_observability_destinations(self, *, params: _T.ListObservabilityDestinationsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListObservabilityDestinations200, _HttpClientResponse], _Errors]: ...
    def list_observability_destinations(self, *, params: _T.ListObservabilityDestinationsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the observability destinations configured for the authenticated entity's default workspace. Use the `workspace_id` query parameter to scope the result to a different workspace. Only destinations with stable release status are surfaced — destinations of other types are excluded. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_OBSERVABILITY_DESTINATIONS, "/observability/destinations", params, None, include_response)

    @_t.overload
    def create_observability_destination(self, *, payload: _T.CreateObservabilityDestinationRequestJson, params: _T.CreateObservabilityDestinationParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateObservabilityDestination201, _Errors]: ...
    @_t.overload
    def create_observability_destination(self, *, payload: _T.CreateObservabilityDestinationRequestJson, params: _T.CreateObservabilityDestinationParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateObservabilityDestination201, _HttpClientResponse], _Errors]: ...
    def create_observability_destination(self, *, payload: _T.CreateObservabilityDestinationRequestJson, params: _T.CreateObservabilityDestinationParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new observability destination. A maximum of 5 destinations per type is allowed. Defaults to the authenticated entity's default workspace; use the `workspace_id` body field to scope to a different workspace. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_OBSERVABILITY_DESTINATION, "/observability/destinations", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_observability_destination(self, id: str, *, params: _T.GetObservabilityDestinationParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetObservabilityDestination200, _Errors]: ...
    @_t.overload
    def get_observability_destination(self, id: str, *, params: _T.GetObservabilityDestinationParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetObservabilityDestination200, _HttpClientResponse], _Errors]: ...
    def get_observability_destination(self, id: str, *, params: _T.GetObservabilityDestinationParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Fetch a single observability destination by its UUID. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_OBSERVABILITY_DESTINATION, f"/observability/destinations/{id}", params, None, include_response)

    @_t.overload
    def delete_observability_destination(self, id: str, *, params: _T.DeleteObservabilityDestinationParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteObservabilityDestination200, _Errors]: ...
    @_t.overload
    def delete_observability_destination(self, id: str, *, params: _T.DeleteObservabilityDestinationParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteObservabilityDestination200, _HttpClientResponse], _Errors]: ...
    def delete_observability_destination(self, id: str, *, params: _T.DeleteObservabilityDestinationParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an existing observability destination. This performs a soft delete. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_OBSERVABILITY_DESTINATION, f"/observability/destinations/{id}", params, None, include_response)

    @_t.overload
    def update_observability_destination(self, id: str, *, payload: _T.UpdateObservabilityDestinationRequestJson, params: _T.UpdateObservabilityDestinationParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateObservabilityDestination200, _Errors]: ...
    @_t.overload
    def update_observability_destination(self, id: str, *, payload: _T.UpdateObservabilityDestinationRequestJson, params: _T.UpdateObservabilityDestinationParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateObservabilityDestination200, _HttpClientResponse], _Errors]: ...
    def update_observability_destination(self, id: str, *, payload: _T.UpdateObservabilityDestinationRequestJson, params: _T.UpdateObservabilityDestinationParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update an existing observability destination. Only the fields provided in the request body are updated. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_OBSERVABILITY_DESTINATION, f"/observability/destinations/{id}", params, _c.json_body(payload), include_response)

    @_t.overload
    def list_organization_members(self, *, params: _T.ListOrganizationMembersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListOrganizationMembers200, _Errors]: ...
    @_t.overload
    def list_organization_members(self, *, params: _T.ListOrganizationMembersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListOrganizationMembers200, _HttpClientResponse], _Errors]: ...
    def list_organization_members(self, *, params: _T.ListOrganizationMembersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all members of the organization associated with the authenticated management key. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_ORGANIZATION_MEMBERS, "/organization/members", params, None, include_response)

    @_t.overload
    def list_presets(self, *, params: _T.ListPresetsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListPresets200, _Errors]: ...
    @_t.overload
    def list_presets(self, *, params: _T.ListPresetsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListPresets200, _HttpClientResponse], _Errors]: ...
    def list_presets(self, *, params: _T.ListPresetsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists all presets for the authenticated user, ordered by most recently updated first."""
        return self._json(_LIST_PRESETS, "/presets", params, None, include_response)

    @_t.overload
    def get_preset(self, slug: str, *, params: _T.GetPresetParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetPreset200, _Errors]: ...
    @_t.overload
    def get_preset(self, slug: str, *, params: _T.GetPresetParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetPreset200, _HttpClientResponse], _Errors]: ...
    def get_preset(self, slug: str, *, params: _T.GetPresetParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a preset by its slug with its currently designated version inline."""
        return self._json(_GET_PRESET, f"/presets/{slug}", params, None, include_response)

    @_t.overload
    def create_presets_chat_completions(self, slug: str, *, payload: _T.CreatePresetsChatCompletionsRequestJson, params: _T.CreatePresetsChatCompletionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreatePresetsChatCompletions200, _Errors]: ...
    @_t.overload
    def create_presets_chat_completions(self, slug: str, *, payload: _T.CreatePresetsChatCompletionsRequestJson, params: _T.CreatePresetsChatCompletionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreatePresetsChatCompletions200, _HttpClientResponse], _Errors]: ...
    def create_presets_chat_completions(self, slug: str, *, payload: _T.CreatePresetsChatCompletionsRequestJson, params: _T.CreatePresetsChatCompletionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a preset (or a new version of an existing one) from an inference request body. Only fields that overlap with the preset config are persisted; other fields (e.g. `messages`, `stream`, `prompt`) are silently ignored."""
        return self._json(_CREATE_PRESETS_CHAT_COMPLETIONS, f"/presets/{slug}/chat/completions", params, _c.json_body(payload), include_response)

    @_t.overload
    def create_presets_messages(self, slug: str, *, payload: _T.CreatePresetsMessagesRequestJson, params: _T.CreatePresetsMessagesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreatePresetsMessages200, _Errors]: ...
    @_t.overload
    def create_presets_messages(self, slug: str, *, payload: _T.CreatePresetsMessagesRequestJson, params: _T.CreatePresetsMessagesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreatePresetsMessages200, _HttpClientResponse], _Errors]: ...
    def create_presets_messages(self, slug: str, *, payload: _T.CreatePresetsMessagesRequestJson, params: _T.CreatePresetsMessagesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a preset (or a new version of an existing one) from an inference request body. Only fields that overlap with the preset config are persisted; other fields (e.g. `messages`, `stream`, `prompt`) are silently ignored."""
        return self._json(_CREATE_PRESETS_MESSAGES, f"/presets/{slug}/messages", params, _c.json_body(payload), include_response)

    @_t.overload
    def create_presets_responses(self, slug: str, *, payload: _T.CreatePresetsResponsesRequestJson, params: _T.CreatePresetsResponsesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreatePresetsResponses200, _Errors]: ...
    @_t.overload
    def create_presets_responses(self, slug: str, *, payload: _T.CreatePresetsResponsesRequestJson, params: _T.CreatePresetsResponsesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreatePresetsResponses200, _HttpClientResponse], _Errors]: ...
    def create_presets_responses(self, slug: str, *, payload: _T.CreatePresetsResponsesRequestJson, params: _T.CreatePresetsResponsesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a preset (or a new version of an existing one) from an inference request body. Only fields that overlap with the preset config are persisted; other fields (e.g. `messages`, `stream`, `prompt`) are silently ignored."""
        return self._json(_CREATE_PRESETS_RESPONSES, f"/presets/{slug}/responses", params, _c.json_body(payload), include_response)

    @_t.overload
    def list_preset_versions(self, slug: str, *, params: _T.ListPresetVersionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListPresetVersions200, _Errors]: ...
    @_t.overload
    def list_preset_versions(self, slug: str, *, params: _T.ListPresetVersionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListPresetVersions200, _HttpClientResponse], _Errors]: ...
    def list_preset_versions(self, slug: str, *, params: _T.ListPresetVersionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists all versions of a preset, ordered by version number ascending (oldest first)."""
        return self._json(_LIST_PRESET_VERSIONS, f"/presets/{slug}/versions", params, None, include_response)

    @_t.overload
    def get_preset_version(self, slug: str, version: str, *, params: _T.GetPresetVersionParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetPresetVersion200, _Errors]: ...
    @_t.overload
    def get_preset_version(self, slug: str, version: str, *, params: _T.GetPresetVersionParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetPresetVersion200, _HttpClientResponse], _Errors]: ...
    def get_preset_version(self, slug: str, version: str, *, params: _T.GetPresetVersionParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a specific version of a preset by its slug and version number."""
        return self._json(_GET_PRESET_VERSION, f"/presets/{slug}/versions/{version}", params, None, include_response)

    @_t.overload
    def list_providers(self, *, params: _T.ListProvidersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProviders200, _Errors]: ...
    @_t.overload
    def list_providers(self, *, params: _T.ListProvidersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProviders200, _HttpClientResponse], _Errors]: ...
    def list_providers(self, *, params: _T.ListProvidersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all providers"""
        return self._json(_LIST_PROVIDERS, "/providers", params, None, include_response)

    @_t.overload
    def create_rerank(self, *, payload: _T.CreateRerankRequestJson, params: _T.CreateRerankParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateRerank200, _Errors]: ...
    @_t.overload
    def create_rerank(self, *, payload: _T.CreateRerankRequestJson, params: _T.CreateRerankParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateRerank200, _HttpClientResponse], _Errors]: ...
    def create_rerank(self, *, payload: _T.CreateRerankRequestJson, params: _T.CreateRerankParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Submits a rerank request to the rerank router"""
        return self._json(_CREATE_RERANK, "/rerank", params, _c.json_body(payload), include_response)

    def create_rerank_sse(self, *, payload: _T.CreateRerankRequestJson, params: _T.CreateRerankParams | None = None) -> _Stream[_sse.DataEvent[_T.CreateRerank200Sse], _SseErrors]:
        """Submits a rerank request to the rerank router"""
        return self._sse(_CREATE_RERANK_SSE, "/rerank", params, _c.json_body(payload), CreateRerank200Sse)

    @_t.overload
    def create_responses(self, *, payload: _T.CreateResponsesRequestJson, params: _T.CreateResponsesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateResponses200, _Errors]: ...
    @_t.overload
    def create_responses(self, *, payload: _T.CreateResponsesRequestJson, params: _T.CreateResponsesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateResponses200, _HttpClientResponse], _Errors]: ...
    def create_responses(self, *, payload: _T.CreateResponsesRequestJson, params: _T.CreateResponsesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a streaming or non-streaming response using OpenResponses API format"""
        return self._json(_CREATE_RESPONSES, "/responses", params, _c.json_body(payload), include_response)

    def create_responses_sse(self, *, payload: _T.CreateResponsesRequestJson, params: _T.CreateResponsesParams | None = None) -> _Stream[_sse.DataEvent[_T.CreateResponses200Sse], _SseErrors]:
        """Creates a streaming or non-streaming response using OpenResponses API format"""
        return self._sse(_CREATE_RESPONSES_SSE, "/responses", params, _c.json_body(payload), CreateResponses200Sse)

    @_t.overload
    def create_videos(self, *, payload: _T.CreateVideosRequestJson, params: _T.CreateVideosParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVideos202, _Errors]: ...
    @_t.overload
    def create_videos(self, *, payload: _T.CreateVideosRequestJson, params: _T.CreateVideosParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVideos202, _HttpClientResponse], _Errors]: ...
    def create_videos(self, *, payload: _T.CreateVideosRequestJson, params: _T.CreateVideosParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Submits a video generation request and returns a polling URL to check status"""
        return self._json(_CREATE_VIDEOS, "/videos", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_videos(self, job_id: str, *, params: _T.GetVideosParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetVideos200, _Errors]: ...
    @_t.overload
    def get_videos(self, job_id: str, *, params: _T.GetVideosParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetVideos200, _HttpClientResponse], _Errors]: ...
    def get_videos(self, job_id: str, *, params: _T.GetVideosParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns job status and content URLs when completed"""
        return self._json(_GET_VIDEOS, f"/videos/{job_id}", params, None, include_response)

    @_t.overload
    def list_videos_content(self, job_id: str, *, params: _T.ListVideosContentParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def list_videos_content(self, job_id: str, *, params: _T.ListVideosContentParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def list_videos_content(self, job_id: str, *, params: _T.ListVideosContentParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Streams the generated video content from the upstream provider"""
        return self._json(_LIST_VIDEOS_CONTENT, f"/videos/{job_id}/content", params, None, include_response)

    @_t.overload
    def list_videos_models(self, *, params: _T.ListVideosModelsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListVideosModels200, _Errors]: ...
    @_t.overload
    def list_videos_models(self, *, params: _T.ListVideosModelsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListVideosModels200, _HttpClientResponse], _Errors]: ...
    def list_videos_models(self, *, params: _T.ListVideosModelsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of all available video generation models and their properties"""
        return self._json(_LIST_VIDEOS_MODELS, "/videos/models", params, None, include_response)

    @_t.overload
    def list_workspaces(self, *, params: _T.ListWorkspacesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListWorkspaces200, _Errors]: ...
    @_t.overload
    def list_workspaces(self, *, params: _T.ListWorkspacesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListWorkspaces200, _HttpClientResponse], _Errors]: ...
    def list_workspaces(self, *, params: _T.ListWorkspacesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all workspaces for the authenticated user. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_WORKSPACES, "/workspaces", params, None, include_response)

    @_t.overload
    def create_workspace(self, *, payload: _T.CreateWorkspaceRequestJson, params: _T.CreateWorkspaceParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateWorkspace201, _Errors]: ...
    @_t.overload
    def create_workspace(self, *, payload: _T.CreateWorkspaceRequestJson, params: _T.CreateWorkspaceParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateWorkspace201, _HttpClientResponse], _Errors]: ...
    def create_workspace(self, *, payload: _T.CreateWorkspaceRequestJson, params: _T.CreateWorkspaceParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new workspace for the authenticated user. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_WORKSPACE, "/workspaces", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_workspace(self, id: str, *, params: _T.GetWorkspaceParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetWorkspace200, _Errors]: ...
    @_t.overload
    def get_workspace(self, id: str, *, params: _T.GetWorkspaceParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetWorkspace200, _HttpClientResponse], _Errors]: ...
    def get_workspace(self, id: str, *, params: _T.GetWorkspaceParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a single workspace by ID or slug. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_WORKSPACE, f"/workspaces/{id}", params, None, include_response)

    @_t.overload
    def delete_workspace(self, id: str, *, params: _T.DeleteWorkspaceParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteWorkspace200, _Errors]: ...
    @_t.overload
    def delete_workspace(self, id: str, *, params: _T.DeleteWorkspaceParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteWorkspace200, _HttpClientResponse], _Errors]: ...
    def delete_workspace(self, id: str, *, params: _T.DeleteWorkspaceParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an existing workspace. The default workspace cannot be deleted. Workspaces with active API keys cannot be deleted; remove the keys first. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_WORKSPACE, f"/workspaces/{id}", params, None, include_response)

    @_t.overload
    def update_workspace(self, id: str, *, payload: _T.UpdateWorkspaceRequestJson, params: _T.UpdateWorkspaceParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateWorkspace200, _Errors]: ...
    @_t.overload
    def update_workspace(self, id: str, *, payload: _T.UpdateWorkspaceRequestJson, params: _T.UpdateWorkspaceParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateWorkspace200, _HttpClientResponse], _Errors]: ...
    def update_workspace(self, id: str, *, payload: _T.UpdateWorkspaceRequestJson, params: _T.UpdateWorkspaceParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update an existing workspace by ID or slug. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_WORKSPACE, f"/workspaces/{id}", params, _c.json_body(payload), include_response)

    @_t.overload
    def list_workspace_budgets(self, id: str, *, params: _T.ListWorkspaceBudgetsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListWorkspaceBudgets200, _Errors]: ...
    @_t.overload
    def list_workspace_budgets(self, id: str, *, params: _T.ListWorkspaceBudgetsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListWorkspaceBudgets200, _HttpClientResponse], _Errors]: ...
    def list_workspace_budgets(self, id: str, *, params: _T.ListWorkspaceBudgetsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all budgets configured for a workspace. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_WORKSPACE_BUDGETS, f"/workspaces/{id}/budgets", params, None, include_response)

    @_t.overload
    def upsert_workspace_budget(self, id: str, interval: str, *, payload: _T.UpsertWorkspaceBudgetRequestJson, params: _T.UpsertWorkspaceBudgetParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpsertWorkspaceBudget200, _Errors]: ...
    @_t.overload
    def upsert_workspace_budget(self, id: str, interval: str, *, payload: _T.UpsertWorkspaceBudgetRequestJson, params: _T.UpsertWorkspaceBudgetParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpsertWorkspaceBudget200, _HttpClientResponse], _Errors]: ...
    def upsert_workspace_budget(self, id: str, interval: str, *, payload: _T.UpsertWorkspaceBudgetRequestJson, params: _T.UpsertWorkspaceBudgetParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create or update the budget for a given interval. Budget limits must strictly decrease as the interval narrows (lifetime > monthly > weekly > daily). [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPSERT_WORKSPACE_BUDGET, f"/workspaces/{id}/budgets/{interval}", params, _c.json_body(payload), include_response)

    @_t.overload
    def delete_workspace_budget(self, id: str, interval: str, *, params: _T.DeleteWorkspaceBudgetParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteWorkspaceBudget200, _Errors]: ...
    @_t.overload
    def delete_workspace_budget(self, id: str, interval: str, *, params: _T.DeleteWorkspaceBudgetParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteWorkspaceBudget200, _HttpClientResponse], _Errors]: ...
    def delete_workspace_budget(self, id: str, interval: str, *, params: _T.DeleteWorkspaceBudgetParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Remove the budget for a given interval. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_WORKSPACE_BUDGET, f"/workspaces/{id}/budgets/{interval}", params, None, include_response)

    @_t.overload
    def list_workspace_members(self, id: str, *, params: _T.ListWorkspaceMembersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListWorkspaceMembers200, _Errors]: ...
    @_t.overload
    def list_workspace_members(self, id: str, *, params: _T.ListWorkspaceMembersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListWorkspaceMembers200, _HttpClientResponse], _Errors]: ...
    def list_workspace_members(self, id: str, *, params: _T.ListWorkspaceMembersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all members of a workspace. Returns paginated results. For the default workspace, returns all organization members (implicit membership). [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_WORKSPACE_MEMBERS, f"/workspaces/{id}/members", params, None, include_response)

    @_t.overload
    def bulk_add_workspace_members(self, id: str, *, payload: _T.BulkAddWorkspaceMembersRequestJson, params: _T.BulkAddWorkspaceMembersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkAddWorkspaceMembers200, _Errors]: ...
    @_t.overload
    def bulk_add_workspace_members(self, id: str, *, payload: _T.BulkAddWorkspaceMembersRequestJson, params: _T.BulkAddWorkspaceMembersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkAddWorkspaceMembers200, _HttpClientResponse], _Errors]: ...
    def bulk_add_workspace_members(self, id: str, *, payload: _T.BulkAddWorkspaceMembersRequestJson, params: _T.BulkAddWorkspaceMembersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Add multiple organization members to a workspace. Members are assigned the same role they hold in the organization. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_ADD_WORKSPACE_MEMBERS, f"/workspaces/{id}/members/add", params, _c.json_body(payload), include_response)

    @_t.overload
    def bulk_remove_workspace_members(self, id: str, *, payload: _T.BulkRemoveWorkspaceMembersRequestJson, params: _T.BulkRemoveWorkspaceMembersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkRemoveWorkspaceMembers200, _Errors]: ...
    @_t.overload
    def bulk_remove_workspace_members(self, id: str, *, payload: _T.BulkRemoveWorkspaceMembersRequestJson, params: _T.BulkRemoveWorkspaceMembersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkRemoveWorkspaceMembers200, _HttpClientResponse], _Errors]: ...
    def bulk_remove_workspace_members(self, id: str, *, payload: _T.BulkRemoveWorkspaceMembersRequestJson, params: _T.BulkRemoveWorkspaceMembersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Remove multiple members from a workspace. Members with active API keys in the workspace cannot be removed. SCIM-managed members cannot be removed; changes must be made in your identity provider. [Management key](/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_REMOVE_WORKSPACE_MEMBERS, f"/workspaces/{id}/members/remove", params, _c.json_body(payload), include_response)


def make(
    http_client: _HttpClientService[_HttpClientError],
    *,
    transform_client: _c.ClientTransform | None = None,
) -> OpenRouterClient:
    """The client over ``http_client`` (requests carry relative paths:
    prepend the API's URL to the client). ``transform_client`` picks the
    client each JSON operation runs on, per call."""
    return OpenRouterClient(http_client, transform_client)


__all__ = ["OpenRouterClient", "OpenRouterClientError", "make"]
