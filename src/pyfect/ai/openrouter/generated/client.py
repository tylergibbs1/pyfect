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
    ActivatePrivateEndpoint200,
    ActivatePrivateEndpoint400,
    ActivatePrivateEndpoint401,
    ActivatePrivateEndpoint403,
    ActivatePrivateEndpoint404,
    ActivatePrivateEndpoint408,
    ActivatePrivateEndpoint409,
    ActivatePrivateEndpoint422,
    ActivatePrivateEndpoint500,
    ActivatePrivateEndpoint502,
    BulkAddWorkspaceMembers200,
    BulkAddWorkspaceMembers400,
    BulkAddWorkspaceMembers401,
    BulkAddWorkspaceMembers403,
    BulkAddWorkspaceMembers404,
    BulkAddWorkspaceMembers500,
    BulkAssignKeysToGuardrail200,
    BulkAssignKeysToGuardrail400,
    BulkAssignKeysToGuardrail401,
    BulkAssignKeysToGuardrail403,
    BulkAssignKeysToGuardrail404,
    BulkAssignKeysToGuardrail500,
    BulkAssignMembersToGuardrail200,
    BulkAssignMembersToGuardrail400,
    BulkAssignMembersToGuardrail401,
    BulkAssignMembersToGuardrail403,
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
    BulkUnassignKeysFromGuardrail403,
    BulkUnassignKeysFromGuardrail404,
    BulkUnassignKeysFromGuardrail500,
    BulkUnassignMembersFromGuardrail200,
    BulkUnassignMembersFromGuardrail400,
    BulkUnassignMembersFromGuardrail401,
    BulkUnassignMembersFromGuardrail403,
    BulkUnassignMembersFromGuardrail404,
    BulkUnassignMembersFromGuardrail500,
    ChangeApiKeyPolicyAssignment200,
    ChangeApiKeyPolicyAssignment400,
    ChangeApiKeyPolicyAssignment401,
    ChangeApiKeyPolicyAssignment403,
    ChangeApiKeyPolicyAssignment404,
    ChangeApiKeyPolicyAssignment409,
    ChangeApiKeyPolicyAssignment500,
    ChangeMemberPolicyAssignment200,
    ChangeMemberPolicyAssignment400,
    ChangeMemberPolicyAssignment401,
    ChangeMemberPolicyAssignment403,
    ChangeMemberPolicyAssignment404,
    ChangeMemberPolicyAssignment409,
    ChangeMemberPolicyAssignment500,
    CopyVaultSecretsToIntern200,
    CopyVaultSecretsToIntern400,
    CopyVaultSecretsToIntern401,
    CopyVaultSecretsToIntern403,
    CopyVaultSecretsToIntern404,
    CopyVaultSecretsToIntern408,
    CopyVaultSecretsToIntern409,
    CopyVaultSecretsToIntern413,
    CopyVaultSecretsToIntern429,
    CopyVaultSecretsToIntern500,
    CopyVaultSecretsToIntern502,
    CopyVaultSecretsToIntern503,
    CopyVaultSecretsToIntern504,
    CreateAccountPolicy201,
    CreateAccountPolicy400,
    CreateAccountPolicy401,
    CreateAccountPolicy403,
    CreateAccountPolicy404,
    CreateAccountPolicy409,
    CreateAccountPolicy500,
    CreateApiAlphaDecisions200,
    CreateApiAlphaDecisions400,
    CreateApiAlphaDecisions401,
    CreateApiAlphaDecisions402,
    CreateApiAlphaDecisions403,
    CreateApiAlphaDecisions404,
    CreateApiAlphaDecisions413,
    CreateApiAlphaDecisions429,
    CreateApiAlphaDecisions500,
    CreateApiAlphaDecisions502,
    CreateApiAlphaDecisions503,
    CreateApiAlphaDecisions524,
    CreateApiAlphaDecisions529,
    CreateApiAlphaExtractions200,
    CreateApiAlphaExtractions400,
    CreateApiAlphaExtractions401,
    CreateApiAlphaExtractions402,
    CreateApiAlphaExtractions403,
    CreateApiAlphaExtractions404,
    CreateApiAlphaExtractions413,
    CreateApiAlphaExtractions429,
    CreateApiAlphaExtractions500,
    CreateApiAlphaExtractions502,
    CreateApiAlphaExtractions503,
    CreateApiAlphaExtractions524,
    CreateApiAlphaExtractions529,
    CreateAudioSpeech400,
    CreateAudioSpeech401,
    CreateAudioSpeech402,
    CreateAudioSpeech403,
    CreateAudioSpeech404,
    CreateAudioSpeech413,
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
    CreateAudioTranscriptions403,
    CreateAudioTranscriptions404,
    CreateAudioTranscriptions413,
    CreateAudioTranscriptions429,
    CreateAudioTranscriptions500,
    CreateAudioTranscriptions502,
    CreateAudioTranscriptions503,
    CreateAudioTranscriptions504,
    CreateAudioTranscriptions524,
    CreateAudioTranscriptions529,
    CreateAuthKeysCode200,
    CreateAuthKeysCode400,
    CreateAuthKeysCode401,
    CreateAuthKeysCode403,
    CreateAuthKeysCode409,
    CreateAuthKeysCode500,
    CreateAuthKeysCode503,
    CreateBYOKKey201,
    CreateBYOKKey400,
    CreateBYOKKey401,
    CreateBYOKKey403,
    CreateBYOKKey500,
    CreateBatches202,
    CreateBatches400,
    CreateBatches401,
    CreateBatches402,
    CreateBatches403,
    CreateBatches404,
    CreateBatches413,
    CreateBatches422,
    CreateBatches429,
    CreateBatches500,
    CreateBatches502,
    CreateBudgetPolicy201,
    CreateBudgetPolicy400,
    CreateBudgetPolicy401,
    CreateBudgetPolicy403,
    CreateBudgetPolicy404,
    CreateBudgetPolicy409,
    CreateBudgetPolicy500,
    CreateCoinbaseCharge410,
    CreateCreditsPurchases202,
    CreateCreditsPurchases400,
    CreateCreditsPurchases401,
    CreateCreditsPurchases402,
    CreateCreditsPurchases403,
    CreateCreditsPurchases404,
    CreateCreditsPurchases409,
    CreateCreditsPurchases429,
    CreateCreditsPurchases500,
    CreateCreditsPurchases503,
    CreateEmbeddings200,
    CreateEmbeddings200Sse,
    CreateEmbeddings400,
    CreateEmbeddings401,
    CreateEmbeddings402,
    CreateEmbeddings403,
    CreateEmbeddings404,
    CreateEmbeddings408,
    CreateEmbeddings413,
    CreateEmbeddings429,
    CreateEmbeddings499,
    CreateEmbeddings500,
    CreateEmbeddings502,
    CreateEmbeddings503,
    CreateEmbeddings504,
    CreateEmbeddings524,
    CreateEmbeddings529,
    CreateExternalUser201,
    CreateExternalUser400,
    CreateExternalUser401,
    CreateExternalUser404,
    CreateExternalUser409,
    CreateExternalUser500,
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
    CreateModelAvailabilityPolicy201,
    CreateModelAvailabilityPolicy400,
    CreateModelAvailabilityPolicy401,
    CreateModelAvailabilityPolicy403,
    CreateModelAvailabilityPolicy404,
    CreateModelAvailabilityPolicy409,
    CreateModelAvailabilityPolicy500,
    CreateModerationPolicy201,
    CreateModerationPolicy400,
    CreateModerationPolicy401,
    CreateModerationPolicy403,
    CreateModerationPolicy404,
    CreateModerationPolicy409,
    CreateModerationPolicy500,
    CreateOauthToken200,
    CreateOauthToken400,
    CreateOauthToken429,
    CreateOauthToken500,
    CreateOauthToken503,
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
    CreatePrivateEndpoint201,
    CreatePrivateEndpoint400,
    CreatePrivateEndpoint401,
    CreatePrivateEndpoint403,
    CreatePrivateEndpoint404,
    CreatePrivateEndpoint408,
    CreatePrivateEndpoint409,
    CreatePrivateEndpoint422,
    CreatePrivateEndpoint500,
    CreatePrivateEndpoint502,
    CreatePrivateProvider201,
    CreatePrivateProvider400,
    CreatePrivateProvider401,
    CreatePrivateProvider403,
    CreatePrivateProvider404,
    CreatePrivateProvider408,
    CreatePrivateProvider409,
    CreatePrivateProvider422,
    CreatePrivateProvider429,
    CreatePrivateProvider500,
    CreatePrivateProvider502,
    CreateRerank200,
    CreateRerank200Sse,
    CreateRerank400,
    CreateRerank401,
    CreateRerank402,
    CreateRerank403,
    CreateRerank404,
    CreateRerank413,
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
    CreateScimGroupMapping201,
    CreateScimGroupMapping400,
    CreateScimGroupMapping401,
    CreateScimGroupMapping403,
    CreateScimGroupMapping404,
    CreateScimGroupMapping409,
    CreateScimGroupMapping500,
    CreateScimSyncJob202,
    CreateScimSyncJob401,
    CreateScimSyncJob403,
    CreateScimSyncJob404,
    CreateScimSyncJob500,
    CreateSystemone200,
    CreateSystemone400,
    CreateSystemone401,
    CreateSystemone402,
    CreateSystemone403,
    CreateSystemone404,
    CreateSystemone413,
    CreateSystemone429,
    CreateSystemone500,
    CreateSystemone502,
    CreateSystemone503,
    CreateSystemone524,
    CreateSystemone529,
    CreateVideos202,
    CreateVideos400,
    CreateVideos401,
    CreateVideos402,
    CreateVideos403,
    CreateVideos404,
    CreateVideos413,
    CreateVideos429,
    CreateVideos499,
    CreateVideos500,
    CreateVideos503,
    CreateWorkspace201,
    CreateWorkspace400,
    CreateWorkspace401,
    CreateWorkspace403,
    CreateWorkspace500,
    DeleteAccountPolicy200,
    DeleteAccountPolicy400,
    DeleteAccountPolicy401,
    DeleteAccountPolicy403,
    DeleteAccountPolicy404,
    DeleteAccountPolicy409,
    DeleteAccountPolicy500,
    DeleteBYOKKey200,
    DeleteBYOKKey401,
    DeleteBYOKKey403,
    DeleteBYOKKey404,
    DeleteBYOKKey500,
    DeleteBatch200,
    DeleteBatch401,
    DeleteBatch404,
    DeleteBatch409,
    DeleteBatch429,
    DeleteBatch500,
    DeleteBatch502,
    DeleteBudgetPolicy200,
    DeleteBudgetPolicy400,
    DeleteBudgetPolicy401,
    DeleteBudgetPolicy403,
    DeleteBudgetPolicy404,
    DeleteBudgetPolicy409,
    DeleteBudgetPolicy500,
    DeleteExternalUser400,
    DeleteExternalUser401,
    DeleteExternalUser404,
    DeleteExternalUser500,
    DeleteFile200,
    DeleteFile401,
    DeleteFile403,
    DeleteFile404,
    DeleteFile429,
    DeleteFile500,
    DeleteFile502,
    DeleteFile503,
    DeleteGuardrail200,
    DeleteGuardrail401,
    DeleteGuardrail403,
    DeleteGuardrail404,
    DeleteGuardrail500,
    DeleteInternVaultSecret400,
    DeleteInternVaultSecret401,
    DeleteInternVaultSecret403,
    DeleteInternVaultSecret404,
    DeleteInternVaultSecret408,
    DeleteInternVaultSecret409,
    DeleteInternVaultSecret429,
    DeleteInternVaultSecret500,
    DeleteInternVaultSecret502,
    DeleteInternVaultSecret503,
    DeleteInternVaultSecret504,
    DeleteKeys200,
    DeleteKeys401,
    DeleteKeys403,
    DeleteKeys404,
    DeleteKeys429,
    DeleteKeys500,
    DeleteModelAvailabilityPolicy200,
    DeleteModelAvailabilityPolicy400,
    DeleteModelAvailabilityPolicy401,
    DeleteModelAvailabilityPolicy403,
    DeleteModelAvailabilityPolicy404,
    DeleteModelAvailabilityPolicy409,
    DeleteModelAvailabilityPolicy500,
    DeleteModerationPolicy200,
    DeleteModerationPolicy400,
    DeleteModerationPolicy401,
    DeleteModerationPolicy403,
    DeleteModerationPolicy404,
    DeleteModerationPolicy409,
    DeleteModerationPolicy500,
    DeleteObservabilityDestination200,
    DeleteObservabilityDestination401,
    DeleteObservabilityDestination403,
    DeleteObservabilityDestination404,
    DeleteObservabilityDestination500,
    DeletePreset200,
    DeletePreset400,
    DeletePreset401,
    DeletePreset403,
    DeletePreset404,
    DeletePreset409,
    DeletePreset500,
    DeletePrivateEndpoint200,
    DeletePrivateEndpoint400,
    DeletePrivateEndpoint401,
    DeletePrivateEndpoint403,
    DeletePrivateEndpoint404,
    DeletePrivateEndpoint408,
    DeletePrivateEndpoint409,
    DeletePrivateEndpoint422,
    DeletePrivateEndpoint500,
    DeletePrivateEndpoint502,
    DeletePrivateProvider200,
    DeletePrivateProvider400,
    DeletePrivateProvider401,
    DeletePrivateProvider403,
    DeletePrivateProvider404,
    DeletePrivateProvider408,
    DeletePrivateProvider409,
    DeletePrivateProvider422,
    DeletePrivateProvider429,
    DeletePrivateProvider500,
    DeletePrivateProvider502,
    DeleteScimGroupMapping200,
    DeleteScimGroupMapping400,
    DeleteScimGroupMapping401,
    DeleteScimGroupMapping403,
    DeleteScimGroupMapping404,
    DeleteScimGroupMapping500,
    DeleteVaultSecret400,
    DeleteVaultSecret401,
    DeleteVaultSecret403,
    DeleteVaultSecret404,
    DeleteVaultSecret408,
    DeleteVaultSecret409,
    DeleteVaultSecret429,
    DeleteVaultSecret500,
    DeleteVaultSecret502,
    DeleteVaultSecret503,
    DeleteVaultSecret504,
    DeleteWorkspace200,
    DeleteWorkspace400,
    DeleteWorkspace401,
    DeleteWorkspace403,
    DeleteWorkspace404,
    DeleteWorkspace500,
    DeleteWorkspaceBudget200,
    DeleteWorkspaceBudget400,
    DeleteWorkspaceBudget401,
    DeleteWorkspaceBudget403,
    DeleteWorkspaceBudget404,
    DeleteWorkspaceBudget500,
    DisablePrivateEndpoint200,
    DisablePrivateEndpoint400,
    DisablePrivateEndpoint401,
    DisablePrivateEndpoint403,
    DisablePrivateEndpoint404,
    DisablePrivateEndpoint408,
    DisablePrivateEndpoint409,
    DisablePrivateEndpoint422,
    DisablePrivateEndpoint500,
    DisablePrivateEndpoint502,
    DownloadContainerFileContent400,
    DownloadContainerFileContent401,
    DownloadContainerFileContent403,
    DownloadContainerFileContent404,
    DownloadContainerFileContent429,
    DownloadContainerFileContent500,
    DownloadContainerFileContent503,
    DownloadFileContent400,
    DownloadFileContent401,
    DownloadFileContent403,
    DownloadFileContent404,
    DownloadFileContent429,
    DownloadFileContent500,
    DownloadFileContent502,
    DownloadFileContent503,
    EnablePrivateEndpoint200,
    EnablePrivateEndpoint400,
    EnablePrivateEndpoint401,
    EnablePrivateEndpoint403,
    EnablePrivateEndpoint404,
    EnablePrivateEndpoint408,
    EnablePrivateEndpoint409,
    EnablePrivateEndpoint422,
    EnablePrivateEndpoint500,
    EnablePrivateEndpoint502,
    ExchangeAuthCodeForAPIKey200,
    ExchangeAuthCodeForAPIKey400,
    ExchangeAuthCodeForAPIKey403,
    ExchangeAuthCodeForAPIKey500,
    GetAnalyticsMeta200,
    GetAnalyticsMeta401,
    GetAnalyticsMeta403,
    GetAnalyticsMeta500,
    GetApiKeyPolicyAssignment200,
    GetApiKeyPolicyAssignment400,
    GetApiKeyPolicyAssignment401,
    GetApiKeyPolicyAssignment403,
    GetApiKeyPolicyAssignment404,
    GetApiKeyPolicyAssignment500,
    GetAppRankings200,
    GetAppRankings400,
    GetAppRankings401,
    GetAppRankings429,
    GetAppRankings500,
    GetBYOKKey200,
    GetBYOKKey401,
    GetBYOKKey403,
    GetBYOKKey404,
    GetBYOKKey500,
    GetBatches200,
    GetBatches401,
    GetBatches402,
    GetBatches404,
    GetBatches410,
    GetBatches429,
    GetBatches500,
    GetBatches502,
    GetBenchmarks200,
    GetBenchmarks400,
    GetBenchmarks401,
    GetBenchmarks429,
    GetBenchmarks500,
    GetBudgetPolicy200,
    GetBudgetPolicy400,
    GetBudgetPolicy401,
    GetBudgetPolicy403,
    GetBudgetPolicy404,
    GetBudgetPolicy500,
    GetContainerFile200,
    GetContainerFile400,
    GetContainerFile401,
    GetContainerFile403,
    GetContainerFile404,
    GetContainerFile429,
    GetContainerFile500,
    GetContainerFile503,
    GetCredits200,
    GetCredits401,
    GetCredits403,
    GetCredits500,
    GetCurrentKey200,
    GetCurrentKey401,
    GetCurrentKey500,
    GetExternalUser200,
    GetExternalUser400,
    GetExternalUser401,
    GetExternalUser403,
    GetExternalUser404,
    GetExternalUser500,
    GetFileMetadata200,
    GetFileMetadata401,
    GetFileMetadata403,
    GetFileMetadata404,
    GetFileMetadata429,
    GetFileMetadata500,
    GetFileMetadata502,
    GetFileMetadata503,
    GetGeneration200,
    GetGeneration400,
    GetGeneration401,
    GetGeneration402,
    GetGeneration403,
    GetGeneration404,
    GetGeneration429,
    GetGeneration500,
    GetGeneration502,
    GetGeneration524,
    GetGeneration529,
    GetGuardrail200,
    GetGuardrail401,
    GetGuardrail403,
    GetGuardrail404,
    GetGuardrail500,
    GetKey200,
    GetKey401,
    GetKey403,
    GetKey404,
    GetKey429,
    GetKey500,
    GetMemberPolicyAssignment200,
    GetMemberPolicyAssignment400,
    GetMemberPolicyAssignment401,
    GetMemberPolicyAssignment403,
    GetMemberPolicyAssignment404,
    GetMemberPolicyAssignment500,
    GetModel200,
    GetModel403,
    GetModel404,
    GetModel500,
    GetModelAvailabilityPolicy200,
    GetModelAvailabilityPolicy400,
    GetModelAvailabilityPolicy401,
    GetModelAvailabilityPolicy403,
    GetModelAvailabilityPolicy404,
    GetModelAvailabilityPolicy500,
    GetModels200,
    GetModels400,
    GetModels401,
    GetModels403,
    GetModels404,
    GetModels408,
    GetModels409,
    GetModels429,
    GetModels500,
    GetModels503,
    GetModerationPolicy200,
    GetModerationPolicy400,
    GetModerationPolicy401,
    GetModerationPolicy403,
    GetModerationPolicy404,
    GetModerationPolicy500,
    GetObservabilityDestination200,
    GetObservabilityDestination401,
    GetObservabilityDestination403,
    GetObservabilityDestination404,
    GetObservabilityDestination500,
    GetOrganizationSettings200,
    GetOrganizationSettings401,
    GetOrganizationSettings403,
    GetOrganizationSettings404,
    GetOrganizationSettings500,
    GetPreset200,
    GetPreset400,
    GetPreset401,
    GetPreset403,
    GetPreset404,
    GetPreset500,
    GetPreset503,
    GetPresetVersion200,
    GetPresetVersion400,
    GetPresetVersion401,
    GetPresetVersion403,
    GetPresetVersion404,
    GetPresetVersion500,
    GetPresetVersion503,
    GetPrivateEndpoint200,
    GetPrivateEndpoint401,
    GetPrivateEndpoint403,
    GetPrivateEndpoint404,
    GetPrivateEndpoint408,
    GetPrivateEndpoint500,
    GetPrivateProvider200,
    GetPrivateProvider401,
    GetPrivateProvider403,
    GetPrivateProvider404,
    GetPrivateProvider500,
    GetRankingsDaily200,
    GetRankingsDaily400,
    GetRankingsDaily401,
    GetRankingsDaily429,
    GetRankingsDaily500,
    GetScimGroupMapping200,
    GetScimGroupMapping401,
    GetScimGroupMapping403,
    GetScimGroupMapping404,
    GetScimGroupMapping500,
    GetScimSyncJob200,
    GetScimSyncJob401,
    GetScimSyncJob403,
    GetScimSyncJob404,
    GetScimSyncJob500,
    GetSessionCost200,
    GetSessionCost400,
    GetSessionCost401,
    GetSessionCost429,
    GetSessionCost500,
    GetTaskClassifications200,
    GetTaskClassifications400,
    GetTaskClassifications401,
    GetTaskClassifications429,
    GetTaskClassifications500,
    GetTool200,
    GetTool401,
    GetTool403,
    GetTool404,
    GetTool500,
    GetUserActivity200,
    GetUserActivity400,
    GetUserActivity401,
    GetUserActivity403,
    GetUserActivity404,
    GetUserActivity500,
    GetVideos200,
    GetVideos401,
    GetVideos403,
    GetVideos404,
    GetVideos500,
    GetWorkspace200,
    GetWorkspace401,
    GetWorkspace403,
    GetWorkspace404,
    GetWorkspace500,
    GetWorkspaceBudget200,
    GetWorkspaceBudget400,
    GetWorkspaceBudget401,
    GetWorkspaceBudget403,
    GetWorkspaceBudget404,
    GetWorkspaceBudget500,
    List200,
    List400,
    List401,
    List403,
    List404,
    List429,
    List500,
    ListAccountPolicies200,
    ListAccountPolicies400,
    ListAccountPolicies401,
    ListAccountPolicies403,
    ListAccountPolicies404,
    ListAccountPolicies500,
    ListBYOKKeys200,
    ListBYOKKeys400,
    ListBYOKKeys401,
    ListBYOKKeys403,
    ListBYOKKeys500,
    ListBatches200,
    ListBatches400,
    ListBatches401,
    ListBatches429,
    ListBatches500,
    ListBatches502,
    ListBudgetPolicies200,
    ListBudgetPolicies400,
    ListBudgetPolicies401,
    ListBudgetPolicies403,
    ListBudgetPolicies404,
    ListBudgetPolicies500,
    ListContainerFiles200,
    ListContainerFiles400,
    ListContainerFiles401,
    ListContainerFiles403,
    ListContainerFiles429,
    ListContainerFiles500,
    ListContainerFiles503,
    ListCreditsPurchases200,
    ListCreditsPurchases400,
    ListCreditsPurchases401,
    ListCreditsPurchases403,
    ListCreditsPurchases404,
    ListCreditsPurchases429,
    ListCreditsPurchases500,
    ListCreditsPurchases503,
    ListEmbeddingsModels200,
    ListEmbeddingsModels400,
    ListEmbeddingsModels500,
    ListEndpoints200,
    ListEndpoints403,
    ListEndpoints404,
    ListEndpoints500,
    ListEndpoints503,
    ListEndpointsZdr200,
    ListEndpointsZdr403,
    ListEndpointsZdr500,
    ListEndpointsZdr503,
    ListExternalUsers200,
    ListExternalUsers400,
    ListExternalUsers401,
    ListExternalUsers403,
    ListExternalUsers404,
    ListExternalUsers500,
    ListFiles200,
    ListFiles400,
    ListFiles401,
    ListFiles403,
    ListFiles429,
    ListFiles500,
    ListFiles502,
    ListFiles503,
    ListGenerationContent200,
    ListGenerationContent400,
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
    ListGuardrailKeyAssignments403,
    ListGuardrailKeyAssignments404,
    ListGuardrailKeyAssignments500,
    ListGuardrailMemberAssignments200,
    ListGuardrailMemberAssignments401,
    ListGuardrailMemberAssignments403,
    ListGuardrailMemberAssignments404,
    ListGuardrailMemberAssignments500,
    ListGuardrails200,
    ListGuardrails400,
    ListGuardrails401,
    ListGuardrails403,
    ListGuardrails500,
    ListImageModelEndpoints200,
    ListImageModelEndpoints404,
    ListImageModelEndpoints500,
    ListImageModels200,
    ListImageModels500,
    ListInternConnections200,
    ListInternConnections400,
    ListInternConnections401,
    ListInternConnections403,
    ListInternConnections404,
    ListInternConnections408,
    ListInternConnections429,
    ListInternConnections500,
    ListInternConnections502,
    ListInternConnections503,
    ListInternConnections504,
    ListInternEffectiveVaultSecrets200,
    ListInternEffectiveVaultSecrets400,
    ListInternEffectiveVaultSecrets401,
    ListInternEffectiveVaultSecrets403,
    ListInternEffectiveVaultSecrets404,
    ListInternEffectiveVaultSecrets408,
    ListInternEffectiveVaultSecrets429,
    ListInternEffectiveVaultSecrets500,
    ListInternEffectiveVaultSecrets502,
    ListInternEffectiveVaultSecrets503,
    ListInternEffectiveVaultSecrets504,
    ListInternVaultSecrets200,
    ListInternVaultSecrets400,
    ListInternVaultSecrets401,
    ListInternVaultSecrets403,
    ListInternVaultSecrets404,
    ListInternVaultSecrets408,
    ListInternVaultSecrets429,
    ListInternVaultSecrets500,
    ListInternVaultSecrets502,
    ListInternVaultSecrets503,
    ListInternVaultSecrets504,
    ListKeyAssignments200,
    ListKeyAssignments400,
    ListKeyAssignments401,
    ListKeyAssignments403,
    ListKeyAssignments404,
    ListKeyAssignments500,
    ListMemberAssignments200,
    ListMemberAssignments400,
    ListMemberAssignments401,
    ListMemberAssignments403,
    ListMemberAssignments404,
    ListMemberAssignments500,
    ListModelAvailabilityPolicies200,
    ListModelAvailabilityPolicies400,
    ListModelAvailabilityPolicies401,
    ListModelAvailabilityPolicies403,
    ListModelAvailabilityPolicies404,
    ListModelAvailabilityPolicies500,
    ListModelsCount200,
    ListModelsCount400,
    ListModelsCount403,
    ListModelsCount500,
    ListModelsUser200,
    ListModelsUser401,
    ListModelsUser403,
    ListModelsUser404,
    ListModelsUser408,
    ListModelsUser409,
    ListModelsUser429,
    ListModelsUser500,
    ListModelsUser503,
    ListModerationPolicies200,
    ListModerationPolicies400,
    ListModerationPolicies401,
    ListModerationPolicies403,
    ListModerationPolicies404,
    ListModerationPolicies500,
    ListOauthJwks200,
    ListOauthJwks500,
    ListObservabilityDestinations200,
    ListObservabilityDestinations400,
    ListObservabilityDestinations401,
    ListObservabilityDestinations403,
    ListObservabilityDestinations500,
    ListOrganizationMembers200,
    ListOrganizationMembers401,
    ListOrganizationMembers403,
    ListOrganizationMembers404,
    ListOrganizationMembers500,
    ListPresetVersions200,
    ListPresetVersions400,
    ListPresetVersions401,
    ListPresetVersions403,
    ListPresetVersions404,
    ListPresetVersions500,
    ListPresetVersions503,
    ListPresets200,
    ListPresets400,
    ListPresets401,
    ListPresets403,
    ListPresets404,
    ListPresets500,
    ListPresets503,
    ListPrivateEndpoints200,
    ListPrivateEndpoints401,
    ListPrivateEndpoints403,
    ListPrivateEndpoints408,
    ListPrivateEndpoints500,
    ListPrivateProviders200,
    ListPrivateProviders401,
    ListPrivateProviders403,
    ListPrivateProviders500,
    ListProviders200,
    ListProviders500,
    ListScimGroupMappings200,
    ListScimGroupMappings401,
    ListScimGroupMappings403,
    ListScimGroupMappings404,
    ListScimGroupMappings500,
    ListScimGroups200,
    ListScimGroups401,
    ListScimGroups403,
    ListScimGroups404,
    ListScimGroups500,
    ListTools200,
    ListTools401,
    ListTools403,
    ListTools404,
    ListTools500,
    ListVaultSecrets200,
    ListVaultSecrets400,
    ListVaultSecrets401,
    ListVaultSecrets403,
    ListVaultSecrets404,
    ListVaultSecrets408,
    ListVaultSecrets429,
    ListVaultSecrets500,
    ListVaultSecrets502,
    ListVaultSecrets503,
    ListVaultSecrets504,
    ListVideosContent400,
    ListVideosContent401,
    ListVideosContent403,
    ListVideosContent404,
    ListVideosContent409,
    ListVideosContent410,
    ListVideosContent500,
    ListVideosContent502,
    ListVideosModels200,
    ListVideosModels400,
    ListVideosModels500,
    ListWorkspaceBudgets200,
    ListWorkspaceBudgets401,
    ListWorkspaceBudgets403,
    ListWorkspaceBudgets404,
    ListWorkspaceBudgets500,
    ListWorkspaceMembers200,
    ListWorkspaceMembers401,
    ListWorkspaceMembers403,
    ListWorkspaceMembers404,
    ListWorkspaceMembers500,
    ListWorkspaces200,
    ListWorkspaces401,
    ListWorkspaces403,
    ListWorkspaces500,
    PromoteContainerFile200,
    PromoteContainerFile400,
    PromoteContainerFile401,
    PromoteContainerFile403,
    PromoteContainerFile404,
    PromoteContainerFile413,
    PromoteContainerFile429,
    PromoteContainerFile499,
    PromoteContainerFile500,
    PromoteContainerFile503,
    QueryAnalytics200,
    QueryAnalytics400,
    QueryAnalytics401,
    QueryAnalytics403,
    QueryAnalytics408,
    QueryAnalytics500,
    RestorePreset200,
    RestorePreset400,
    RestorePreset401,
    RestorePreset403,
    RestorePreset404,
    RestorePreset409,
    RestorePreset500,
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
    StoreInternVaultSecret200,
    StoreInternVaultSecret400,
    StoreInternVaultSecret401,
    StoreInternVaultSecret403,
    StoreInternVaultSecret404,
    StoreInternVaultSecret408,
    StoreInternVaultSecret409,
    StoreInternVaultSecret413,
    StoreInternVaultSecret429,
    StoreInternVaultSecret500,
    StoreInternVaultSecret502,
    StoreInternVaultSecret503,
    StoreInternVaultSecret504,
    StoreVaultSecret200,
    StoreVaultSecret400,
    StoreVaultSecret401,
    StoreVaultSecret403,
    StoreVaultSecret404,
    StoreVaultSecret408,
    StoreVaultSecret409,
    StoreVaultSecret413,
    StoreVaultSecret429,
    StoreVaultSecret500,
    StoreVaultSecret502,
    StoreVaultSecret503,
    StoreVaultSecret504,
    SubmitGenerationFeedback200,
    SubmitGenerationFeedback400,
    SubmitGenerationFeedback401,
    SubmitGenerationFeedback403,
    SubmitGenerationFeedback404,
    SubmitGenerationFeedback409,
    SubmitGenerationFeedback429,
    SubmitGenerationFeedback500,
    SubmitGenerationFeedback503,
    UpdateAccountPolicy200,
    UpdateAccountPolicy400,
    UpdateAccountPolicy401,
    UpdateAccountPolicy403,
    UpdateAccountPolicy404,
    UpdateAccountPolicy409,
    UpdateAccountPolicy500,
    UpdateBYOKKey200,
    UpdateBYOKKey400,
    UpdateBYOKKey401,
    UpdateBYOKKey403,
    UpdateBYOKKey404,
    UpdateBYOKKey409,
    UpdateBYOKKey500,
    UpdateBudgetPolicy200,
    UpdateBudgetPolicy400,
    UpdateBudgetPolicy401,
    UpdateBudgetPolicy403,
    UpdateBudgetPolicy404,
    UpdateBudgetPolicy409,
    UpdateBudgetPolicy500,
    UpdateExternalUser200,
    UpdateExternalUser400,
    UpdateExternalUser401,
    UpdateExternalUser404,
    UpdateExternalUser500,
    UpdateGuardrail200,
    UpdateGuardrail400,
    UpdateGuardrail401,
    UpdateGuardrail403,
    UpdateGuardrail404,
    UpdateGuardrail409,
    UpdateGuardrail500,
    UpdateKeys200,
    UpdateKeys400,
    UpdateKeys401,
    UpdateKeys403,
    UpdateKeys404,
    UpdateKeys409,
    UpdateKeys429,
    UpdateKeys500,
    UpdateModelAvailabilityPolicy200,
    UpdateModelAvailabilityPolicy400,
    UpdateModelAvailabilityPolicy401,
    UpdateModelAvailabilityPolicy403,
    UpdateModelAvailabilityPolicy404,
    UpdateModelAvailabilityPolicy409,
    UpdateModelAvailabilityPolicy500,
    UpdateModerationPolicy200,
    UpdateModerationPolicy400,
    UpdateModerationPolicy401,
    UpdateModerationPolicy403,
    UpdateModerationPolicy404,
    UpdateModerationPolicy409,
    UpdateModerationPolicy500,
    UpdateObservabilityDestination200,
    UpdateObservabilityDestination400,
    UpdateObservabilityDestination401,
    UpdateObservabilityDestination403,
    UpdateObservabilityDestination404,
    UpdateObservabilityDestination409,
    UpdateObservabilityDestination500,
    UpdateOrganizationSettings200,
    UpdateOrganizationSettings400,
    UpdateOrganizationSettings401,
    UpdateOrganizationSettings403,
    UpdateOrganizationSettings404,
    UpdateOrganizationSettings500,
    UpdatePrivateEndpoint200,
    UpdatePrivateEndpoint400,
    UpdatePrivateEndpoint401,
    UpdatePrivateEndpoint403,
    UpdatePrivateEndpoint404,
    UpdatePrivateEndpoint408,
    UpdatePrivateEndpoint409,
    UpdatePrivateEndpoint422,
    UpdatePrivateEndpoint500,
    UpdatePrivateEndpoint502,
    UpdatePrivateProvider200,
    UpdatePrivateProvider400,
    UpdatePrivateProvider401,
    UpdatePrivateProvider403,
    UpdatePrivateProvider404,
    UpdatePrivateProvider408,
    UpdatePrivateProvider409,
    UpdatePrivateProvider422,
    UpdatePrivateProvider429,
    UpdatePrivateProvider500,
    UpdatePrivateProvider502,
    UpdateScimGroupMapping200,
    UpdateScimGroupMapping400,
    UpdateScimGroupMapping401,
    UpdateScimGroupMapping403,
    UpdateScimGroupMapping404,
    UpdateScimGroupMapping500,
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
    UploadFile499,
    UploadFile500,
    UploadFile502,
    UploadFile503,
    UpsertWorkspaceBudget200,
    UpsertWorkspaceBudget400,
    UpsertWorkspaceBudget401,
    UpsertWorkspaceBudget403,
    UpsertWorkspaceBudget404,
    UpsertWorkspaceBudget500,
    ValidatePrivateEndpoint200,
    ValidatePrivateEndpoint400,
    ValidatePrivateEndpoint401,
    ValidatePrivateEndpoint403,
    ValidatePrivateEndpoint404,
    ValidatePrivateEndpoint408,
    ValidatePrivateEndpoint409,
    ValidatePrivateEndpoint422,
    ValidatePrivateEndpoint500,
    ValidatePrivateEndpoint502,
)


class OpenRouterClientError(_c.ClientError):
    """A documented error status of an operation."""


type _Errors = _HttpClientError | _S.SchemaError | OpenRouterClientError
type _PlainErrors = _HttpClientError | _S.SchemaError
type _SseErrors = _HttpClientError | _S.SchemaError | _sse.Retry | _sse.SseError

_GET_USER_ACTIVITY = _c.Operation("GET", url_params=('date', 'api_key_hash', 'user_id', 'group_by', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetUserActivity200, errors={400: ('GetUserActivity400', GetUserActivity400), 401: ('GetUserActivity401', GetUserActivity401), 403: ('GetUserActivity403', GetUserActivity403), 404: ('GetUserActivity404', GetUserActivity404), 500: ('GetUserActivity500', GetUserActivity500)})
_GET_ANALYTICS_META = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetAnalyticsMeta200, errors={401: ('GetAnalyticsMeta401', GetAnalyticsMeta401), 403: ('GetAnalyticsMeta403', GetAnalyticsMeta403), 500: ('GetAnalyticsMeta500', GetAnalyticsMeta500)})
_QUERY_ANALYTICS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=QueryAnalytics200, errors={400: ('QueryAnalytics400', QueryAnalytics400), 401: ('QueryAnalytics401', QueryAnalytics401), 403: ('QueryAnalytics403', QueryAnalytics403), 408: ('QueryAnalytics408', QueryAnalytics408), 500: ('QueryAnalytics500', QueryAnalytics500)})
_CREATE_API_ALPHA_DECISIONS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateApiAlphaDecisions200, errors={400: ('CreateApiAlphaDecisions400', CreateApiAlphaDecisions400), 401: ('CreateApiAlphaDecisions401', CreateApiAlphaDecisions401), 402: ('CreateApiAlphaDecisions402', CreateApiAlphaDecisions402), 403: ('CreateApiAlphaDecisions403', CreateApiAlphaDecisions403), 404: ('CreateApiAlphaDecisions404', CreateApiAlphaDecisions404), 413: ('CreateApiAlphaDecisions413', CreateApiAlphaDecisions413), 429: ('CreateApiAlphaDecisions429', CreateApiAlphaDecisions429), 500: ('CreateApiAlphaDecisions500', CreateApiAlphaDecisions500), 502: ('CreateApiAlphaDecisions502', CreateApiAlphaDecisions502), 503: ('CreateApiAlphaDecisions503', CreateApiAlphaDecisions503), 524: ('CreateApiAlphaDecisions524', CreateApiAlphaDecisions524), 529: ('CreateApiAlphaDecisions529', CreateApiAlphaDecisions529)})
_CREATE_API_ALPHA_EXTRACTIONS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateApiAlphaExtractions200, errors={400: ('CreateApiAlphaExtractions400', CreateApiAlphaExtractions400), 401: ('CreateApiAlphaExtractions401', CreateApiAlphaExtractions401), 402: ('CreateApiAlphaExtractions402', CreateApiAlphaExtractions402), 403: ('CreateApiAlphaExtractions403', CreateApiAlphaExtractions403), 404: ('CreateApiAlphaExtractions404', CreateApiAlphaExtractions404), 413: ('CreateApiAlphaExtractions413', CreateApiAlphaExtractions413), 429: ('CreateApiAlphaExtractions429', CreateApiAlphaExtractions429), 500: ('CreateApiAlphaExtractions500', CreateApiAlphaExtractions500), 502: ('CreateApiAlphaExtractions502', CreateApiAlphaExtractions502), 503: ('CreateApiAlphaExtractions503', CreateApiAlphaExtractions503), 524: ('CreateApiAlphaExtractions524', CreateApiAlphaExtractions524), 529: ('CreateApiAlphaExtractions529', CreateApiAlphaExtractions529)})
_CREATE_AUDIO_SPEECH = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), binary_success=True, errors={400: ('CreateAudioSpeech400', CreateAudioSpeech400), 401: ('CreateAudioSpeech401', CreateAudioSpeech401), 402: ('CreateAudioSpeech402', CreateAudioSpeech402), 403: ('CreateAudioSpeech403', CreateAudioSpeech403), 404: ('CreateAudioSpeech404', CreateAudioSpeech404), 413: ('CreateAudioSpeech413', CreateAudioSpeech413), 429: ('CreateAudioSpeech429', CreateAudioSpeech429), 500: ('CreateAudioSpeech500', CreateAudioSpeech500), 502: ('CreateAudioSpeech502', CreateAudioSpeech502), 503: ('CreateAudioSpeech503', CreateAudioSpeech503), 524: ('CreateAudioSpeech524', CreateAudioSpeech524), 529: ('CreateAudioSpeech529', CreateAudioSpeech529)})
_CREATE_AUDIO_SPEECH_STREAM = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_CREATE_AUDIO_TRANSCRIPTIONS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateAudioTranscriptions200, errors={400: ('CreateAudioTranscriptions400', CreateAudioTranscriptions400), 401: ('CreateAudioTranscriptions401', CreateAudioTranscriptions401), 402: ('CreateAudioTranscriptions402', CreateAudioTranscriptions402), 403: ('CreateAudioTranscriptions403', CreateAudioTranscriptions403), 404: ('CreateAudioTranscriptions404', CreateAudioTranscriptions404), 413: ('CreateAudioTranscriptions413', CreateAudioTranscriptions413), 429: ('CreateAudioTranscriptions429', CreateAudioTranscriptions429), 500: ('CreateAudioTranscriptions500', CreateAudioTranscriptions500), 502: ('CreateAudioTranscriptions502', CreateAudioTranscriptions502), 503: ('CreateAudioTranscriptions503', CreateAudioTranscriptions503), 504: ('CreateAudioTranscriptions504', CreateAudioTranscriptions504), 524: ('CreateAudioTranscriptions524', CreateAudioTranscriptions524), 529: ('CreateAudioTranscriptions529', CreateAudioTranscriptions529)})
_EXCHANGE_AUTH_CODE_FOR_API_KEY = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ExchangeAuthCodeForAPIKey200, errors={400: ('ExchangeAuthCodeForAPIKey400', ExchangeAuthCodeForAPIKey400), 403: ('ExchangeAuthCodeForAPIKey403', ExchangeAuthCodeForAPIKey403), 500: ('ExchangeAuthCodeForAPIKey500', ExchangeAuthCodeForAPIKey500)})
_CREATE_AUTH_KEYS_CODE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateAuthKeysCode200, errors={400: ('CreateAuthKeysCode400', CreateAuthKeysCode400), 401: ('CreateAuthKeysCode401', CreateAuthKeysCode401), 403: ('CreateAuthKeysCode403', CreateAuthKeysCode403), 409: ('CreateAuthKeysCode409', CreateAuthKeysCode409), 500: ('CreateAuthKeysCode500', CreateAuthKeysCode500), 503: ('CreateAuthKeysCode503', CreateAuthKeysCode503)})
_LIST_BATCHES = _c.Operation("GET", url_params=('limit', 'after', 'status', 'created_after', 'created_before', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListBatches200, errors={400: ('ListBatches400', ListBatches400), 401: ('ListBatches401', ListBatches401), 429: ('ListBatches429', ListBatches429), 500: ('ListBatches500', ListBatches500), 502: ('ListBatches502', ListBatches502)})
_CREATE_BATCHES = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateBatches202, errors={400: ('CreateBatches400', CreateBatches400), 401: ('CreateBatches401', CreateBatches401), 402: ('CreateBatches402', CreateBatches402), 403: ('CreateBatches403', CreateBatches403), 404: ('CreateBatches404', CreateBatches404), 413: ('CreateBatches413', CreateBatches413), 422: ('CreateBatches422', CreateBatches422), 429: ('CreateBatches429', CreateBatches429), 500: ('CreateBatches500', CreateBatches500), 502: ('CreateBatches502', CreateBatches502)})
_GET_BATCHES = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetBatches200, errors={401: ('GetBatches401', GetBatches401), 402: ('GetBatches402', GetBatches402), 404: ('GetBatches404', GetBatches404), 410: ('GetBatches410', GetBatches410), 429: ('GetBatches429', GetBatches429), 500: ('GetBatches500', GetBatches500), 502: ('GetBatches502', GetBatches502)})
_DELETE_BATCH = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteBatch200, errors={401: ('DeleteBatch401', DeleteBatch401), 404: ('DeleteBatch404', DeleteBatch404), 409: ('DeleteBatch409', DeleteBatch409), 429: ('DeleteBatch429', DeleteBatch429), 500: ('DeleteBatch500', DeleteBatch500), 502: ('DeleteBatch502', DeleteBatch502)})
_GET_BENCHMARKS = _c.Operation("GET", url_params=('source', 'task_type', 'benchmark_type', 'include_run_config', 'search_engine', 'search_surface', 'arena', 'category', 'max_results', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetBenchmarks200, errors={400: ('GetBenchmarks400', GetBenchmarks400), 401: ('GetBenchmarks401', GetBenchmarks401), 429: ('GetBenchmarks429', GetBenchmarks429), 500: ('GetBenchmarks500', GetBenchmarks500)})
_LIST_BYOK_KEYS = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', 'provider', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListBYOKKeys200, errors={400: ('ListBYOKKeys400', ListBYOKKeys400), 401: ('ListBYOKKeys401', ListBYOKKeys401), 403: ('ListBYOKKeys403', ListBYOKKeys403), 500: ('ListBYOKKeys500', ListBYOKKeys500)})
_CREATE_BYOK_KEY = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateBYOKKey201, errors={400: ('CreateBYOKKey400', CreateBYOKKey400), 401: ('CreateBYOKKey401', CreateBYOKKey401), 403: ('CreateBYOKKey403', CreateBYOKKey403), 500: ('CreateBYOKKey500', CreateBYOKKey500)})
_GET_BYOK_KEY = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetBYOKKey200, errors={401: ('GetBYOKKey401', GetBYOKKey401), 403: ('GetBYOKKey403', GetBYOKKey403), 404: ('GetBYOKKey404', GetBYOKKey404), 500: ('GetBYOKKey500', GetBYOKKey500)})
_DELETE_BYOK_KEY = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteBYOKKey200, errors={401: ('DeleteBYOKKey401', DeleteBYOKKey401), 403: ('DeleteBYOKKey403', DeleteBYOKKey403), 404: ('DeleteBYOKKey404', DeleteBYOKKey404), 500: ('DeleteBYOKKey500', DeleteBYOKKey500)})
_UPDATE_BYOK_KEY = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateBYOKKey200, errors={400: ('UpdateBYOKKey400', UpdateBYOKKey400), 401: ('UpdateBYOKKey401', UpdateBYOKKey401), 403: ('UpdateBYOKKey403', UpdateBYOKKey403), 404: ('UpdateBYOKKey404', UpdateBYOKKey404), 409: ('UpdateBYOKKey409', UpdateBYOKKey409), 500: ('UpdateBYOKKey500', UpdateBYOKKey500)})
_SEND_CHAT_COMPLETION_REQUEST = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ), success=SendChatCompletionRequest200, errors={400: ('SendChatCompletionRequest400', SendChatCompletionRequest400), 401: ('SendChatCompletionRequest401', SendChatCompletionRequest401), 402: ('SendChatCompletionRequest402', SendChatCompletionRequest402), 403: ('SendChatCompletionRequest403', SendChatCompletionRequest403), 404: ('SendChatCompletionRequest404', SendChatCompletionRequest404), 408: ('SendChatCompletionRequest408', SendChatCompletionRequest408), 413: ('SendChatCompletionRequest413', SendChatCompletionRequest413), 422: ('SendChatCompletionRequest422', SendChatCompletionRequest422), 429: ('SendChatCompletionRequest429', SendChatCompletionRequest429), 500: ('SendChatCompletionRequest500', SendChatCompletionRequest500), 502: ('SendChatCompletionRequest502', SendChatCompletionRequest502), 503: ('SendChatCompletionRequest503', SendChatCompletionRequest503), 524: ('SendChatCompletionRequest524', SendChatCompletionRequest524), 529: ('SendChatCompletionRequest529', SendChatCompletionRequest529)})
_SEND_CHAT_COMPLETION_REQUEST_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ))
_GET_TASK_CLASSIFICATIONS = _c.Operation("GET", url_params=('window', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetTaskClassifications200, errors={400: ('GetTaskClassifications400', GetTaskClassifications400), 401: ('GetTaskClassifications401', GetTaskClassifications401), 429: ('GetTaskClassifications429', GetTaskClassifications429), 500: ('GetTaskClassifications500', GetTaskClassifications500)})
_LIST_CONTAINER_FILES = _c.Operation("GET", url_params=('limit', 'after', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListContainerFiles200, errors={400: ('ListContainerFiles400', ListContainerFiles400), 401: ('ListContainerFiles401', ListContainerFiles401), 403: ('ListContainerFiles403', ListContainerFiles403), 429: ('ListContainerFiles429', ListContainerFiles429), 500: ('ListContainerFiles500', ListContainerFiles500), 503: ('ListContainerFiles503', ListContainerFiles503)})
_GET_CONTAINER_FILE = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetContainerFile200, errors={400: ('GetContainerFile400', GetContainerFile400), 401: ('GetContainerFile401', GetContainerFile401), 403: ('GetContainerFile403', GetContainerFile403), 404: ('GetContainerFile404', GetContainerFile404), 429: ('GetContainerFile429', GetContainerFile429), 500: ('GetContainerFile500', GetContainerFile500), 503: ('GetContainerFile503', GetContainerFile503)})
_DOWNLOAD_CONTAINER_FILE_CONTENT = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), binary_success=True, errors={400: ('DownloadContainerFileContent400', DownloadContainerFileContent400), 401: ('DownloadContainerFileContent401', DownloadContainerFileContent401), 403: ('DownloadContainerFileContent403', DownloadContainerFileContent403), 404: ('DownloadContainerFileContent404', DownloadContainerFileContent404), 429: ('DownloadContainerFileContent429', DownloadContainerFileContent429), 500: ('DownloadContainerFileContent500', DownloadContainerFileContent500), 503: ('DownloadContainerFileContent503', DownloadContainerFileContent503)})
_DOWNLOAD_CONTAINER_FILE_CONTENT_STREAM = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_PROMOTE_CONTAINER_FILE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=PromoteContainerFile200, errors={400: ('PromoteContainerFile400', PromoteContainerFile400), 401: ('PromoteContainerFile401', PromoteContainerFile401), 403: ('PromoteContainerFile403', PromoteContainerFile403), 404: ('PromoteContainerFile404', PromoteContainerFile404), 413: ('PromoteContainerFile413', PromoteContainerFile413), 429: ('PromoteContainerFile429', PromoteContainerFile429), 499: ('PromoteContainerFile499', PromoteContainerFile499), 500: ('PromoteContainerFile500', PromoteContainerFile500), 503: ('PromoteContainerFile503', PromoteContainerFile503)})
_GET_CREDITS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetCredits200, errors={401: ('GetCredits401', GetCredits401), 403: ('GetCredits403', GetCredits403), 500: ('GetCredits500', GetCredits500)})
_CREATE_COINBASE_CHARGE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), void=(200, ), errors={410: ('CreateCoinbaseCharge410', CreateCoinbaseCharge410)})
_CREATE_CREDITS_PURCHASES = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'idempotency-key', ), success=CreateCreditsPurchases202, errors={400: ('CreateCreditsPurchases400', CreateCreditsPurchases400), 401: ('CreateCreditsPurchases401', CreateCreditsPurchases401), 402: ('CreateCreditsPurchases402', CreateCreditsPurchases402), 403: ('CreateCreditsPurchases403', CreateCreditsPurchases403), 404: ('CreateCreditsPurchases404', CreateCreditsPurchases404), 409: ('CreateCreditsPurchases409', CreateCreditsPurchases409), 429: ('CreateCreditsPurchases429', CreateCreditsPurchases429), 500: ('CreateCreditsPurchases500', CreateCreditsPurchases500), 503: ('CreateCreditsPurchases503', CreateCreditsPurchases503)})
_LIST_CREDITS_PURCHASES = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListCreditsPurchases200, errors={400: ('ListCreditsPurchases400', ListCreditsPurchases400), 401: ('ListCreditsPurchases401', ListCreditsPurchases401), 403: ('ListCreditsPurchases403', ListCreditsPurchases403), 404: ('ListCreditsPurchases404', ListCreditsPurchases404), 429: ('ListCreditsPurchases429', ListCreditsPurchases429), 500: ('ListCreditsPurchases500', ListCreditsPurchases500), 503: ('ListCreditsPurchases503', ListCreditsPurchases503)})
_GET_APP_RANKINGS = _c.Operation("GET", url_params=('category', 'subcategory', 'sort', 'start_date', 'end_date', 'limit', 'offset', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetAppRankings200, errors={400: ('GetAppRankings400', GetAppRankings400), 401: ('GetAppRankings401', GetAppRankings401), 429: ('GetAppRankings429', GetAppRankings429), 500: ('GetAppRankings500', GetAppRankings500)})
_GET_RANKINGS_DAILY = _c.Operation("GET", url_params=('start_date', 'end_date', 'period', 'modality', 'context_bucket', 'category', 'language_type', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetRankingsDaily200, errors={400: ('GetRankingsDaily400', GetRankingsDaily400), 401: ('GetRankingsDaily401', GetRankingsDaily401), 429: ('GetRankingsDaily429', GetRankingsDaily429), 500: ('GetRankingsDaily500', GetRankingsDaily500)})
_GET_SESSION_COST = _c.Operation("GET", url_params=('app_slug', 'model', 'turn_range', 'limit', 'offset', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetSessionCost200, errors={400: ('GetSessionCost400', GetSessionCost400), 401: ('GetSessionCost401', GetSessionCost401), 429: ('GetSessionCost429', GetSessionCost429), 500: ('GetSessionCost500', GetSessionCost500)})
_CREATE_EMBEDDINGS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateEmbeddings200, errors={400: ('CreateEmbeddings400', CreateEmbeddings400), 401: ('CreateEmbeddings401', CreateEmbeddings401), 402: ('CreateEmbeddings402', CreateEmbeddings402), 403: ('CreateEmbeddings403', CreateEmbeddings403), 404: ('CreateEmbeddings404', CreateEmbeddings404), 408: ('CreateEmbeddings408', CreateEmbeddings408), 413: ('CreateEmbeddings413', CreateEmbeddings413), 429: ('CreateEmbeddings429', CreateEmbeddings429), 499: ('CreateEmbeddings499', CreateEmbeddings499), 500: ('CreateEmbeddings500', CreateEmbeddings500), 502: ('CreateEmbeddings502', CreateEmbeddings502), 503: ('CreateEmbeddings503', CreateEmbeddings503), 504: ('CreateEmbeddings504', CreateEmbeddings504), 524: ('CreateEmbeddings524', CreateEmbeddings524), 529: ('CreateEmbeddings529', CreateEmbeddings529)})
_CREATE_EMBEDDINGS_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_LIST_EMBEDDINGS_MODELS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListEmbeddingsModels200, errors={400: ('ListEmbeddingsModels400', ListEmbeddingsModels400), 500: ('ListEmbeddingsModels500', ListEmbeddingsModels500)})
_LIST_ENDPOINTS_ZDR = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListEndpointsZdr200, errors={403: ('ListEndpointsZdr403', ListEndpointsZdr403), 500: ('ListEndpointsZdr500', ListEndpointsZdr500), 503: ('ListEndpointsZdr503', ListEndpointsZdr503)})
_LIST_EXTERNAL_USERS = _c.Operation("GET", url_params=('offset', 'limit', 'user', 'include_inactive', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListExternalUsers200, errors={400: ('ListExternalUsers400', ListExternalUsers400), 401: ('ListExternalUsers401', ListExternalUsers401), 403: ('ListExternalUsers403', ListExternalUsers403), 404: ('ListExternalUsers404', ListExternalUsers404), 500: ('ListExternalUsers500', ListExternalUsers500)})
_CREATE_EXTERNAL_USER = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateExternalUser201, errors={400: ('CreateExternalUser400', CreateExternalUser400), 401: ('CreateExternalUser401', CreateExternalUser401), 404: ('CreateExternalUser404', CreateExternalUser404), 409: ('CreateExternalUser409', CreateExternalUser409), 500: ('CreateExternalUser500', CreateExternalUser500)})
_GET_EXTERNAL_USER = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetExternalUser200, errors={400: ('GetExternalUser400', GetExternalUser400), 401: ('GetExternalUser401', GetExternalUser401), 403: ('GetExternalUser403', GetExternalUser403), 404: ('GetExternalUser404', GetExternalUser404), 500: ('GetExternalUser500', GetExternalUser500)})
_DELETE_EXTERNAL_USER = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), void=(204, ), errors={400: ('DeleteExternalUser400', DeleteExternalUser400), 401: ('DeleteExternalUser401', DeleteExternalUser401), 404: ('DeleteExternalUser404', DeleteExternalUser404), 500: ('DeleteExternalUser500', DeleteExternalUser500)})
_UPDATE_EXTERNAL_USER = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateExternalUser200, errors={400: ('UpdateExternalUser400', UpdateExternalUser400), 401: ('UpdateExternalUser401', UpdateExternalUser401), 404: ('UpdateExternalUser404', UpdateExternalUser404), 500: ('UpdateExternalUser500', UpdateExternalUser500)})
_LIST_FILES = _c.Operation("GET", url_params=('limit', 'cursor', 'workspace_id', 'provider', 'after', 'after_id', 'before_id', 'order', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListFiles200, errors={400: ('ListFiles400', ListFiles400), 401: ('ListFiles401', ListFiles401), 403: ('ListFiles403', ListFiles403), 429: ('ListFiles429', ListFiles429), 500: ('ListFiles500', ListFiles500), 502: ('ListFiles502', ListFiles502), 503: ('ListFiles503', ListFiles503)})
_UPLOAD_FILE = _c.Operation("POST", url_params=('workspace_id', 'provider', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UploadFile200, errors={400: ('UploadFile400', UploadFile400), 401: ('UploadFile401', UploadFile401), 403: ('UploadFile403', UploadFile403), 413: ('UploadFile413', UploadFile413), 429: ('UploadFile429', UploadFile429), 499: ('UploadFile499', UploadFile499), 500: ('UploadFile500', UploadFile500), 502: ('UploadFile502', UploadFile502), 503: ('UploadFile503', UploadFile503)})
_GET_FILE_METADATA = _c.Operation("GET", url_params=('workspace_id', 'provider', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetFileMetadata200, errors={401: ('GetFileMetadata401', GetFileMetadata401), 403: ('GetFileMetadata403', GetFileMetadata403), 404: ('GetFileMetadata404', GetFileMetadata404), 429: ('GetFileMetadata429', GetFileMetadata429), 500: ('GetFileMetadata500', GetFileMetadata500), 502: ('GetFileMetadata502', GetFileMetadata502), 503: ('GetFileMetadata503', GetFileMetadata503)})
_DELETE_FILE = _c.Operation("DELETE", url_params=('workspace_id', 'provider', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteFile200, errors={401: ('DeleteFile401', DeleteFile401), 403: ('DeleteFile403', DeleteFile403), 404: ('DeleteFile404', DeleteFile404), 429: ('DeleteFile429', DeleteFile429), 500: ('DeleteFile500', DeleteFile500), 502: ('DeleteFile502', DeleteFile502), 503: ('DeleteFile503', DeleteFile503)})
_DOWNLOAD_FILE_CONTENT = _c.Operation("GET", url_params=('workspace_id', 'provider', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), binary_success=True, errors={400: ('DownloadFileContent400', DownloadFileContent400), 401: ('DownloadFileContent401', DownloadFileContent401), 403: ('DownloadFileContent403', DownloadFileContent403), 404: ('DownloadFileContent404', DownloadFileContent404), 429: ('DownloadFileContent429', DownloadFileContent429), 500: ('DownloadFileContent500', DownloadFileContent500), 502: ('DownloadFileContent502', DownloadFileContent502), 503: ('DownloadFileContent503', DownloadFileContent503)})
_DOWNLOAD_FILE_CONTENT_STREAM = _c.Operation("GET", url_params=('workspace_id', 'provider', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_GET_GENERATION = _c.Operation("GET", url_params=('id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetGeneration200, errors={400: ('GetGeneration400', GetGeneration400), 401: ('GetGeneration401', GetGeneration401), 402: ('GetGeneration402', GetGeneration402), 403: ('GetGeneration403', GetGeneration403), 404: ('GetGeneration404', GetGeneration404), 429: ('GetGeneration429', GetGeneration429), 500: ('GetGeneration500', GetGeneration500), 502: ('GetGeneration502', GetGeneration502), 524: ('GetGeneration524', GetGeneration524), 529: ('GetGeneration529', GetGeneration529)})
_LIST_GENERATION_CONTENT = _c.Operation("GET", url_params=('id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListGenerationContent200, errors={400: ('ListGenerationContent400', ListGenerationContent400), 401: ('ListGenerationContent401', ListGenerationContent401), 403: ('ListGenerationContent403', ListGenerationContent403), 404: ('ListGenerationContent404', ListGenerationContent404), 429: ('ListGenerationContent429', ListGenerationContent429), 500: ('ListGenerationContent500', ListGenerationContent500), 502: ('ListGenerationContent502', ListGenerationContent502), 524: ('ListGenerationContent524', ListGenerationContent524), 529: ('ListGenerationContent529', ListGenerationContent529)})
_SUBMIT_GENERATION_FEEDBACK = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=SubmitGenerationFeedback200, errors={400: ('SubmitGenerationFeedback400', SubmitGenerationFeedback400), 401: ('SubmitGenerationFeedback401', SubmitGenerationFeedback401), 403: ('SubmitGenerationFeedback403', SubmitGenerationFeedback403), 404: ('SubmitGenerationFeedback404', SubmitGenerationFeedback404), 409: ('SubmitGenerationFeedback409', SubmitGenerationFeedback409), 429: ('SubmitGenerationFeedback429', SubmitGenerationFeedback429), 500: ('SubmitGenerationFeedback500', SubmitGenerationFeedback500), 503: ('SubmitGenerationFeedback503', SubmitGenerationFeedback503)})
_LIST_GUARDRAILS = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListGuardrails200, errors={400: ('ListGuardrails400', ListGuardrails400), 401: ('ListGuardrails401', ListGuardrails401), 403: ('ListGuardrails403', ListGuardrails403), 500: ('ListGuardrails500', ListGuardrails500)})
_CREATE_GUARDRAIL = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateGuardrail201, errors={400: ('CreateGuardrail400', CreateGuardrail400), 401: ('CreateGuardrail401', CreateGuardrail401), 403: ('CreateGuardrail403', CreateGuardrail403), 500: ('CreateGuardrail500', CreateGuardrail500)})
_GET_GUARDRAIL = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetGuardrail200, errors={401: ('GetGuardrail401', GetGuardrail401), 403: ('GetGuardrail403', GetGuardrail403), 404: ('GetGuardrail404', GetGuardrail404), 500: ('GetGuardrail500', GetGuardrail500)})
_DELETE_GUARDRAIL = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteGuardrail200, errors={401: ('DeleteGuardrail401', DeleteGuardrail401), 403: ('DeleteGuardrail403', DeleteGuardrail403), 404: ('DeleteGuardrail404', DeleteGuardrail404), 500: ('DeleteGuardrail500', DeleteGuardrail500)})
_UPDATE_GUARDRAIL = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateGuardrail200, errors={400: ('UpdateGuardrail400', UpdateGuardrail400), 401: ('UpdateGuardrail401', UpdateGuardrail401), 403: ('UpdateGuardrail403', UpdateGuardrail403), 404: ('UpdateGuardrail404', UpdateGuardrail404), 409: ('UpdateGuardrail409', UpdateGuardrail409), 500: ('UpdateGuardrail500', UpdateGuardrail500)})
_LIST_GUARDRAIL_KEY_ASSIGNMENTS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListGuardrailKeyAssignments200, errors={401: ('ListGuardrailKeyAssignments401', ListGuardrailKeyAssignments401), 403: ('ListGuardrailKeyAssignments403', ListGuardrailKeyAssignments403), 404: ('ListGuardrailKeyAssignments404', ListGuardrailKeyAssignments404), 500: ('ListGuardrailKeyAssignments500', ListGuardrailKeyAssignments500)})
_BULK_ASSIGN_KEYS_TO_GUARDRAIL = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkAssignKeysToGuardrail200, errors={400: ('BulkAssignKeysToGuardrail400', BulkAssignKeysToGuardrail400), 401: ('BulkAssignKeysToGuardrail401', BulkAssignKeysToGuardrail401), 403: ('BulkAssignKeysToGuardrail403', BulkAssignKeysToGuardrail403), 404: ('BulkAssignKeysToGuardrail404', BulkAssignKeysToGuardrail404), 500: ('BulkAssignKeysToGuardrail500', BulkAssignKeysToGuardrail500)})
_BULK_UNASSIGN_KEYS_FROM_GUARDRAIL = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkUnassignKeysFromGuardrail200, errors={400: ('BulkUnassignKeysFromGuardrail400', BulkUnassignKeysFromGuardrail400), 401: ('BulkUnassignKeysFromGuardrail401', BulkUnassignKeysFromGuardrail401), 403: ('BulkUnassignKeysFromGuardrail403', BulkUnassignKeysFromGuardrail403), 404: ('BulkUnassignKeysFromGuardrail404', BulkUnassignKeysFromGuardrail404), 500: ('BulkUnassignKeysFromGuardrail500', BulkUnassignKeysFromGuardrail500)})
_LIST_GUARDRAIL_MEMBER_ASSIGNMENTS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListGuardrailMemberAssignments200, errors={401: ('ListGuardrailMemberAssignments401', ListGuardrailMemberAssignments401), 403: ('ListGuardrailMemberAssignments403', ListGuardrailMemberAssignments403), 404: ('ListGuardrailMemberAssignments404', ListGuardrailMemberAssignments404), 500: ('ListGuardrailMemberAssignments500', ListGuardrailMemberAssignments500)})
_BULK_ASSIGN_MEMBERS_TO_GUARDRAIL = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkAssignMembersToGuardrail200, errors={400: ('BulkAssignMembersToGuardrail400', BulkAssignMembersToGuardrail400), 401: ('BulkAssignMembersToGuardrail401', BulkAssignMembersToGuardrail401), 403: ('BulkAssignMembersToGuardrail403', BulkAssignMembersToGuardrail403), 404: ('BulkAssignMembersToGuardrail404', BulkAssignMembersToGuardrail404), 500: ('BulkAssignMembersToGuardrail500', BulkAssignMembersToGuardrail500)})
_BULK_UNASSIGN_MEMBERS_FROM_GUARDRAIL = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkUnassignMembersFromGuardrail200, errors={400: ('BulkUnassignMembersFromGuardrail400', BulkUnassignMembersFromGuardrail400), 401: ('BulkUnassignMembersFromGuardrail401', BulkUnassignMembersFromGuardrail401), 403: ('BulkUnassignMembersFromGuardrail403', BulkUnassignMembersFromGuardrail403), 404: ('BulkUnassignMembersFromGuardrail404', BulkUnassignMembersFromGuardrail404), 500: ('BulkUnassignMembersFromGuardrail500', BulkUnassignMembersFromGuardrail500)})
_LIST_KEY_ASSIGNMENTS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListKeyAssignments200, errors={400: ('ListKeyAssignments400', ListKeyAssignments400), 401: ('ListKeyAssignments401', ListKeyAssignments401), 403: ('ListKeyAssignments403', ListKeyAssignments403), 404: ('ListKeyAssignments404', ListKeyAssignments404), 500: ('ListKeyAssignments500', ListKeyAssignments500)})
_LIST_MEMBER_ASSIGNMENTS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListMemberAssignments200, errors={400: ('ListMemberAssignments400', ListMemberAssignments400), 401: ('ListMemberAssignments401', ListMemberAssignments401), 403: ('ListMemberAssignments403', ListMemberAssignments403), 404: ('ListMemberAssignments404', ListMemberAssignments404), 500: ('ListMemberAssignments500', ListMemberAssignments500)})
_LIST_ACCOUNT_POLICIES = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListAccountPolicies200, errors={400: ('ListAccountPolicies400', ListAccountPolicies400), 401: ('ListAccountPolicies401', ListAccountPolicies401), 403: ('ListAccountPolicies403', ListAccountPolicies403), 404: ('ListAccountPolicies404', ListAccountPolicies404), 500: ('ListAccountPolicies500', ListAccountPolicies500)})
_CREATE_ACCOUNT_POLICY = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateAccountPolicy201, errors={400: ('CreateAccountPolicy400', CreateAccountPolicy400), 401: ('CreateAccountPolicy401', CreateAccountPolicy401), 403: ('CreateAccountPolicy403', CreateAccountPolicy403), 404: ('CreateAccountPolicy404', CreateAccountPolicy404), 409: ('CreateAccountPolicy409', CreateAccountPolicy409), 500: ('CreateAccountPolicy500', CreateAccountPolicy500)})
_UPDATE_ACCOUNT_POLICY = _c.Operation("PUT", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateAccountPolicy200, errors={400: ('UpdateAccountPolicy400', UpdateAccountPolicy400), 401: ('UpdateAccountPolicy401', UpdateAccountPolicy401), 403: ('UpdateAccountPolicy403', UpdateAccountPolicy403), 404: ('UpdateAccountPolicy404', UpdateAccountPolicy404), 409: ('UpdateAccountPolicy409', UpdateAccountPolicy409), 500: ('UpdateAccountPolicy500', UpdateAccountPolicy500)})
_DELETE_ACCOUNT_POLICY = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteAccountPolicy200, errors={400: ('DeleteAccountPolicy400', DeleteAccountPolicy400), 401: ('DeleteAccountPolicy401', DeleteAccountPolicy401), 403: ('DeleteAccountPolicy403', DeleteAccountPolicy403), 404: ('DeleteAccountPolicy404', DeleteAccountPolicy404), 409: ('DeleteAccountPolicy409', DeleteAccountPolicy409), 500: ('DeleteAccountPolicy500', DeleteAccountPolicy500)})
_GET_API_KEY_POLICY_ASSIGNMENT = _c.Operation("GET", url_params=('workspace_id', 'policy_type', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetApiKeyPolicyAssignment200, errors={400: ('GetApiKeyPolicyAssignment400', GetApiKeyPolicyAssignment400), 401: ('GetApiKeyPolicyAssignment401', GetApiKeyPolicyAssignment401), 403: ('GetApiKeyPolicyAssignment403', GetApiKeyPolicyAssignment403), 404: ('GetApiKeyPolicyAssignment404', GetApiKeyPolicyAssignment404), 500: ('GetApiKeyPolicyAssignment500', GetApiKeyPolicyAssignment500)})
_CHANGE_API_KEY_POLICY_ASSIGNMENT = _c.Operation("PUT", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ChangeApiKeyPolicyAssignment200, errors={400: ('ChangeApiKeyPolicyAssignment400', ChangeApiKeyPolicyAssignment400), 401: ('ChangeApiKeyPolicyAssignment401', ChangeApiKeyPolicyAssignment401), 403: ('ChangeApiKeyPolicyAssignment403', ChangeApiKeyPolicyAssignment403), 404: ('ChangeApiKeyPolicyAssignment404', ChangeApiKeyPolicyAssignment404), 409: ('ChangeApiKeyPolicyAssignment409', ChangeApiKeyPolicyAssignment409), 500: ('ChangeApiKeyPolicyAssignment500', ChangeApiKeyPolicyAssignment500)})
_GET_MEMBER_POLICY_ASSIGNMENT = _c.Operation("GET", url_params=('workspace_id', 'policy_type', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetMemberPolicyAssignment200, errors={400: ('GetMemberPolicyAssignment400', GetMemberPolicyAssignment400), 401: ('GetMemberPolicyAssignment401', GetMemberPolicyAssignment401), 403: ('GetMemberPolicyAssignment403', GetMemberPolicyAssignment403), 404: ('GetMemberPolicyAssignment404', GetMemberPolicyAssignment404), 500: ('GetMemberPolicyAssignment500', GetMemberPolicyAssignment500)})
_CHANGE_MEMBER_POLICY_ASSIGNMENT = _c.Operation("PUT", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ChangeMemberPolicyAssignment200, errors={400: ('ChangeMemberPolicyAssignment400', ChangeMemberPolicyAssignment400), 401: ('ChangeMemberPolicyAssignment401', ChangeMemberPolicyAssignment401), 403: ('ChangeMemberPolicyAssignment403', ChangeMemberPolicyAssignment403), 404: ('ChangeMemberPolicyAssignment404', ChangeMemberPolicyAssignment404), 409: ('ChangeMemberPolicyAssignment409', ChangeMemberPolicyAssignment409), 500: ('ChangeMemberPolicyAssignment500', ChangeMemberPolicyAssignment500)})
_LIST_BUDGET_POLICIES = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListBudgetPolicies200, errors={400: ('ListBudgetPolicies400', ListBudgetPolicies400), 401: ('ListBudgetPolicies401', ListBudgetPolicies401), 403: ('ListBudgetPolicies403', ListBudgetPolicies403), 404: ('ListBudgetPolicies404', ListBudgetPolicies404), 500: ('ListBudgetPolicies500', ListBudgetPolicies500)})
_CREATE_BUDGET_POLICY = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateBudgetPolicy201, errors={400: ('CreateBudgetPolicy400', CreateBudgetPolicy400), 401: ('CreateBudgetPolicy401', CreateBudgetPolicy401), 403: ('CreateBudgetPolicy403', CreateBudgetPolicy403), 404: ('CreateBudgetPolicy404', CreateBudgetPolicy404), 409: ('CreateBudgetPolicy409', CreateBudgetPolicy409), 500: ('CreateBudgetPolicy500', CreateBudgetPolicy500)})
_GET_BUDGET_POLICY = _c.Operation("GET", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetBudgetPolicy200, errors={400: ('GetBudgetPolicy400', GetBudgetPolicy400), 401: ('GetBudgetPolicy401', GetBudgetPolicy401), 403: ('GetBudgetPolicy403', GetBudgetPolicy403), 404: ('GetBudgetPolicy404', GetBudgetPolicy404), 500: ('GetBudgetPolicy500', GetBudgetPolicy500)})
_UPDATE_BUDGET_POLICY = _c.Operation("PUT", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateBudgetPolicy200, errors={400: ('UpdateBudgetPolicy400', UpdateBudgetPolicy400), 401: ('UpdateBudgetPolicy401', UpdateBudgetPolicy401), 403: ('UpdateBudgetPolicy403', UpdateBudgetPolicy403), 404: ('UpdateBudgetPolicy404', UpdateBudgetPolicy404), 409: ('UpdateBudgetPolicy409', UpdateBudgetPolicy409), 500: ('UpdateBudgetPolicy500', UpdateBudgetPolicy500)})
_DELETE_BUDGET_POLICY = _c.Operation("DELETE", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteBudgetPolicy200, errors={400: ('DeleteBudgetPolicy400', DeleteBudgetPolicy400), 401: ('DeleteBudgetPolicy401', DeleteBudgetPolicy401), 403: ('DeleteBudgetPolicy403', DeleteBudgetPolicy403), 404: ('DeleteBudgetPolicy404', DeleteBudgetPolicy404), 409: ('DeleteBudgetPolicy409', DeleteBudgetPolicy409), 500: ('DeleteBudgetPolicy500', DeleteBudgetPolicy500)})
_LIST_MODEL_AVAILABILITY_POLICIES = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListModelAvailabilityPolicies200, errors={400: ('ListModelAvailabilityPolicies400', ListModelAvailabilityPolicies400), 401: ('ListModelAvailabilityPolicies401', ListModelAvailabilityPolicies401), 403: ('ListModelAvailabilityPolicies403', ListModelAvailabilityPolicies403), 404: ('ListModelAvailabilityPolicies404', ListModelAvailabilityPolicies404), 500: ('ListModelAvailabilityPolicies500', ListModelAvailabilityPolicies500)})
_CREATE_MODEL_AVAILABILITY_POLICY = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateModelAvailabilityPolicy201, errors={400: ('CreateModelAvailabilityPolicy400', CreateModelAvailabilityPolicy400), 401: ('CreateModelAvailabilityPolicy401', CreateModelAvailabilityPolicy401), 403: ('CreateModelAvailabilityPolicy403', CreateModelAvailabilityPolicy403), 404: ('CreateModelAvailabilityPolicy404', CreateModelAvailabilityPolicy404), 409: ('CreateModelAvailabilityPolicy409', CreateModelAvailabilityPolicy409), 500: ('CreateModelAvailabilityPolicy500', CreateModelAvailabilityPolicy500)})
_GET_MODEL_AVAILABILITY_POLICY = _c.Operation("GET", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetModelAvailabilityPolicy200, errors={400: ('GetModelAvailabilityPolicy400', GetModelAvailabilityPolicy400), 401: ('GetModelAvailabilityPolicy401', GetModelAvailabilityPolicy401), 403: ('GetModelAvailabilityPolicy403', GetModelAvailabilityPolicy403), 404: ('GetModelAvailabilityPolicy404', GetModelAvailabilityPolicy404), 500: ('GetModelAvailabilityPolicy500', GetModelAvailabilityPolicy500)})
_UPDATE_MODEL_AVAILABILITY_POLICY = _c.Operation("PUT", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateModelAvailabilityPolicy200, errors={400: ('UpdateModelAvailabilityPolicy400', UpdateModelAvailabilityPolicy400), 401: ('UpdateModelAvailabilityPolicy401', UpdateModelAvailabilityPolicy401), 403: ('UpdateModelAvailabilityPolicy403', UpdateModelAvailabilityPolicy403), 404: ('UpdateModelAvailabilityPolicy404', UpdateModelAvailabilityPolicy404), 409: ('UpdateModelAvailabilityPolicy409', UpdateModelAvailabilityPolicy409), 500: ('UpdateModelAvailabilityPolicy500', UpdateModelAvailabilityPolicy500)})
_DELETE_MODEL_AVAILABILITY_POLICY = _c.Operation("DELETE", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteModelAvailabilityPolicy200, errors={400: ('DeleteModelAvailabilityPolicy400', DeleteModelAvailabilityPolicy400), 401: ('DeleteModelAvailabilityPolicy401', DeleteModelAvailabilityPolicy401), 403: ('DeleteModelAvailabilityPolicy403', DeleteModelAvailabilityPolicy403), 404: ('DeleteModelAvailabilityPolicy404', DeleteModelAvailabilityPolicy404), 409: ('DeleteModelAvailabilityPolicy409', DeleteModelAvailabilityPolicy409), 500: ('DeleteModelAvailabilityPolicy500', DeleteModelAvailabilityPolicy500)})
_LIST_MODERATION_POLICIES = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListModerationPolicies200, errors={400: ('ListModerationPolicies400', ListModerationPolicies400), 401: ('ListModerationPolicies401', ListModerationPolicies401), 403: ('ListModerationPolicies403', ListModerationPolicies403), 404: ('ListModerationPolicies404', ListModerationPolicies404), 500: ('ListModerationPolicies500', ListModerationPolicies500)})
_CREATE_MODERATION_POLICY = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateModerationPolicy201, errors={400: ('CreateModerationPolicy400', CreateModerationPolicy400), 401: ('CreateModerationPolicy401', CreateModerationPolicy401), 403: ('CreateModerationPolicy403', CreateModerationPolicy403), 404: ('CreateModerationPolicy404', CreateModerationPolicy404), 409: ('CreateModerationPolicy409', CreateModerationPolicy409), 500: ('CreateModerationPolicy500', CreateModerationPolicy500)})
_GET_MODERATION_POLICY = _c.Operation("GET", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetModerationPolicy200, errors={400: ('GetModerationPolicy400', GetModerationPolicy400), 401: ('GetModerationPolicy401', GetModerationPolicy401), 403: ('GetModerationPolicy403', GetModerationPolicy403), 404: ('GetModerationPolicy404', GetModerationPolicy404), 500: ('GetModerationPolicy500', GetModerationPolicy500)})
_UPDATE_MODERATION_POLICY = _c.Operation("PUT", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateModerationPolicy200, errors={400: ('UpdateModerationPolicy400', UpdateModerationPolicy400), 401: ('UpdateModerationPolicy401', UpdateModerationPolicy401), 403: ('UpdateModerationPolicy403', UpdateModerationPolicy403), 404: ('UpdateModerationPolicy404', UpdateModerationPolicy404), 409: ('UpdateModerationPolicy409', UpdateModerationPolicy409), 500: ('UpdateModerationPolicy500', UpdateModerationPolicy500)})
_DELETE_MODERATION_POLICY = _c.Operation("DELETE", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteModerationPolicy200, errors={400: ('DeleteModerationPolicy400', DeleteModerationPolicy400), 401: ('DeleteModerationPolicy401', DeleteModerationPolicy401), 403: ('DeleteModerationPolicy403', DeleteModerationPolicy403), 404: ('DeleteModerationPolicy404', DeleteModerationPolicy404), 409: ('DeleteModerationPolicy409', DeleteModerationPolicy409), 500: ('DeleteModerationPolicy500', DeleteModerationPolicy500)})
_CREATE_IMAGES = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateImages200, errors={400: ('CreateImages400', CreateImages400), 401: ('CreateImages401', CreateImages401), 402: ('CreateImages402', CreateImages402), 403: ('CreateImages403', CreateImages403), 404: ('CreateImages404', CreateImages404), 413: ('CreateImages413', CreateImages413), 429: ('CreateImages429', CreateImages429), 500: ('CreateImages500', CreateImages500), 502: ('CreateImages502', CreateImages502), 524: ('CreateImages524', CreateImages524), 529: ('CreateImages529', CreateImages529)})
_CREATE_IMAGES_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_LIST_IMAGE_MODELS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListImageModels200, errors={500: ('ListImageModels500', ListImageModels500)})
_LIST_IMAGE_MODEL_ENDPOINTS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListImageModelEndpoints200, errors={404: ('ListImageModelEndpoints404', ListImageModelEndpoints404), 500: ('ListImageModelEndpoints500', ListImageModelEndpoints500)})
_GET_CURRENT_KEY = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetCurrentKey200, errors={401: ('GetCurrentKey401', GetCurrentKey401), 500: ('GetCurrentKey500', GetCurrentKey500)})
_LIST = _c.Operation("GET", url_params=('include_disabled', 'include_expired', 'offset', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=List200, errors={400: ('List400', List400), 401: ('List401', List401), 403: ('List403', List403), 404: ('List404', List404), 429: ('List429', List429), 500: ('List500', List500)})
_CREATE_KEYS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateKeys201, errors={400: ('CreateKeys400', CreateKeys400), 401: ('CreateKeys401', CreateKeys401), 403: ('CreateKeys403', CreateKeys403), 429: ('CreateKeys429', CreateKeys429), 500: ('CreateKeys500', CreateKeys500)})
_GET_KEY = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetKey200, errors={401: ('GetKey401', GetKey401), 403: ('GetKey403', GetKey403), 404: ('GetKey404', GetKey404), 429: ('GetKey429', GetKey429), 500: ('GetKey500', GetKey500)})
_DELETE_KEYS = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteKeys200, errors={401: ('DeleteKeys401', DeleteKeys401), 403: ('DeleteKeys403', DeleteKeys403), 404: ('DeleteKeys404', DeleteKeys404), 429: ('DeleteKeys429', DeleteKeys429), 500: ('DeleteKeys500', DeleteKeys500)})
_UPDATE_KEYS = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateKeys200, errors={400: ('UpdateKeys400', UpdateKeys400), 401: ('UpdateKeys401', UpdateKeys401), 403: ('UpdateKeys403', UpdateKeys403), 404: ('UpdateKeys404', UpdateKeys404), 409: ('UpdateKeys409', UpdateKeys409), 429: ('UpdateKeys429', UpdateKeys429), 500: ('UpdateKeys500', UpdateKeys500)})
_CREATE_MESSAGES = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ), success=CreateMessages200, errors={400: ('CreateMessages400', CreateMessages400), 401: ('CreateMessages401', CreateMessages401), 403: ('CreateMessages403', CreateMessages403), 404: ('CreateMessages404', CreateMessages404), 429: ('CreateMessages429', CreateMessages429), 500: ('CreateMessages500', CreateMessages500), 503: ('CreateMessages503', CreateMessages503), 529: ('CreateMessages529', CreateMessages529)})
_CREATE_MESSAGES_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ))
_GET_MODEL = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetModel200, errors={403: ('GetModel403', GetModel403), 404: ('GetModel404', GetModel404), 500: ('GetModel500', GetModel500)})
_GET_MODELS = _c.Operation("GET", url_params=('offset', 'limit', 'category', 'supported_parameters', 'output_modalities', 'sort', 'q', 'input_modalities', 'endpoints', 'context', 'min_price', 'max_price', 'arch', 'model_authors', 'providers', 'distillable', 'zdr', 'region', 'min_output_price', 'max_output_price', 'min_age_days', 'max_age_days', 'min_intelligence_index', 'max_intelligence_index', 'min_coding_index', 'max_coding_index', 'min_agentic_index', 'max_agentic_index', 'min_tool_success_rate', 'max_tool_success_rate', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetModels200, errors={400: ('GetModels400', GetModels400), 401: ('GetModels401', GetModels401), 403: ('GetModels403', GetModels403), 404: ('GetModels404', GetModels404), 408: ('GetModels408', GetModels408), 409: ('GetModels409', GetModels409), 429: ('GetModels429', GetModels429), 500: ('GetModels500', GetModels500), 503: ('GetModels503', GetModels503)})
_LIST_ENDPOINTS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListEndpoints200, errors={403: ('ListEndpoints403', ListEndpoints403), 404: ('ListEndpoints404', ListEndpoints404), 500: ('ListEndpoints500', ListEndpoints500), 503: ('ListEndpoints503', ListEndpoints503)})
_LIST_MODELS_COUNT = _c.Operation("GET", url_params=('output_modalities', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListModelsCount200, errors={400: ('ListModelsCount400', ListModelsCount400), 403: ('ListModelsCount403', ListModelsCount403), 500: ('ListModelsCount500', ListModelsCount500)})
_LIST_MODELS_USER = _c.Operation("GET", url_params=('offset', 'limit', 'output_modalities', 'sort', 'client', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListModelsUser200, errors={401: ('ListModelsUser401', ListModelsUser401), 403: ('ListModelsUser403', ListModelsUser403), 404: ('ListModelsUser404', ListModelsUser404), 408: ('ListModelsUser408', ListModelsUser408), 409: ('ListModelsUser409', ListModelsUser409), 429: ('ListModelsUser429', ListModelsUser429), 500: ('ListModelsUser500', ListModelsUser500), 503: ('ListModelsUser503', ListModelsUser503)})
_LIST_OAUTH_JWKS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListOauthJwks200, errors={500: ('ListOauthJwks500', ListOauthJwks500)})
_CREATE_OAUTH_TOKEN = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateOauthToken200, errors={400: ('CreateOauthToken400', CreateOauthToken400), 429: ('CreateOauthToken429', CreateOauthToken429), 500: ('CreateOauthToken500', CreateOauthToken500), 503: ('CreateOauthToken503', CreateOauthToken503)})
_LIST_OBSERVABILITY_DESTINATIONS = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListObservabilityDestinations200, errors={400: ('ListObservabilityDestinations400', ListObservabilityDestinations400), 401: ('ListObservabilityDestinations401', ListObservabilityDestinations401), 403: ('ListObservabilityDestinations403', ListObservabilityDestinations403), 500: ('ListObservabilityDestinations500', ListObservabilityDestinations500)})
_CREATE_OBSERVABILITY_DESTINATION = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateObservabilityDestination201, errors={400: ('CreateObservabilityDestination400', CreateObservabilityDestination400), 401: ('CreateObservabilityDestination401', CreateObservabilityDestination401), 403: ('CreateObservabilityDestination403', CreateObservabilityDestination403), 409: ('CreateObservabilityDestination409', CreateObservabilityDestination409), 500: ('CreateObservabilityDestination500', CreateObservabilityDestination500)})
_GET_OBSERVABILITY_DESTINATION = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetObservabilityDestination200, errors={401: ('GetObservabilityDestination401', GetObservabilityDestination401), 403: ('GetObservabilityDestination403', GetObservabilityDestination403), 404: ('GetObservabilityDestination404', GetObservabilityDestination404), 500: ('GetObservabilityDestination500', GetObservabilityDestination500)})
_DELETE_OBSERVABILITY_DESTINATION = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteObservabilityDestination200, errors={401: ('DeleteObservabilityDestination401', DeleteObservabilityDestination401), 403: ('DeleteObservabilityDestination403', DeleteObservabilityDestination403), 404: ('DeleteObservabilityDestination404', DeleteObservabilityDestination404), 500: ('DeleteObservabilityDestination500', DeleteObservabilityDestination500)})
_UPDATE_OBSERVABILITY_DESTINATION = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateObservabilityDestination200, errors={400: ('UpdateObservabilityDestination400', UpdateObservabilityDestination400), 401: ('UpdateObservabilityDestination401', UpdateObservabilityDestination401), 403: ('UpdateObservabilityDestination403', UpdateObservabilityDestination403), 404: ('UpdateObservabilityDestination404', UpdateObservabilityDestination404), 409: ('UpdateObservabilityDestination409', UpdateObservabilityDestination409), 500: ('UpdateObservabilityDestination500', UpdateObservabilityDestination500)})
_LIST_ORGANIZATION_MEMBERS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListOrganizationMembers200, errors={401: ('ListOrganizationMembers401', ListOrganizationMembers401), 403: ('ListOrganizationMembers403', ListOrganizationMembers403), 404: ('ListOrganizationMembers404', ListOrganizationMembers404), 500: ('ListOrganizationMembers500', ListOrganizationMembers500)})
_GET_ORGANIZATION_SETTINGS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetOrganizationSettings200, errors={401: ('GetOrganizationSettings401', GetOrganizationSettings401), 403: ('GetOrganizationSettings403', GetOrganizationSettings403), 404: ('GetOrganizationSettings404', GetOrganizationSettings404), 500: ('GetOrganizationSettings500', GetOrganizationSettings500)})
_UPDATE_ORGANIZATION_SETTINGS = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateOrganizationSettings200, errors={400: ('UpdateOrganizationSettings400', UpdateOrganizationSettings400), 401: ('UpdateOrganizationSettings401', UpdateOrganizationSettings401), 403: ('UpdateOrganizationSettings403', UpdateOrganizationSettings403), 404: ('UpdateOrganizationSettings404', UpdateOrganizationSettings404), 500: ('UpdateOrganizationSettings500', UpdateOrganizationSettings500)})
_LIST_PRESETS = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListPresets200, errors={400: ('ListPresets400', ListPresets400), 401: ('ListPresets401', ListPresets401), 403: ('ListPresets403', ListPresets403), 404: ('ListPresets404', ListPresets404), 500: ('ListPresets500', ListPresets500), 503: ('ListPresets503', ListPresets503)})
_GET_PRESET = _c.Operation("GET", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetPreset200, errors={400: ('GetPreset400', GetPreset400), 401: ('GetPreset401', GetPreset401), 403: ('GetPreset403', GetPreset403), 404: ('GetPreset404', GetPreset404), 500: ('GetPreset500', GetPreset500), 503: ('GetPreset503', GetPreset503)})
_DELETE_PRESET = _c.Operation("DELETE", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeletePreset200, errors={400: ('DeletePreset400', DeletePreset400), 401: ('DeletePreset401', DeletePreset401), 403: ('DeletePreset403', DeletePreset403), 404: ('DeletePreset404', DeletePreset404), 409: ('DeletePreset409', DeletePreset409), 500: ('DeletePreset500', DeletePreset500)})
_CREATE_PRESETS_CHAT_COMPLETIONS = _c.Operation("POST", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreatePresetsChatCompletions200, errors={400: ('CreatePresetsChatCompletions400', CreatePresetsChatCompletions400), 401: ('CreatePresetsChatCompletions401', CreatePresetsChatCompletions401), 403: ('CreatePresetsChatCompletions403', CreatePresetsChatCompletions403), 404: ('CreatePresetsChatCompletions404', CreatePresetsChatCompletions404), 409: ('CreatePresetsChatCompletions409', CreatePresetsChatCompletions409), 500: ('CreatePresetsChatCompletions500', CreatePresetsChatCompletions500)})
_CREATE_PRESETS_MESSAGES = _c.Operation("POST", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreatePresetsMessages200, errors={400: ('CreatePresetsMessages400', CreatePresetsMessages400), 401: ('CreatePresetsMessages401', CreatePresetsMessages401), 403: ('CreatePresetsMessages403', CreatePresetsMessages403), 404: ('CreatePresetsMessages404', CreatePresetsMessages404), 409: ('CreatePresetsMessages409', CreatePresetsMessages409), 500: ('CreatePresetsMessages500', CreatePresetsMessages500)})
_CREATE_PRESETS_RESPONSES = _c.Operation("POST", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreatePresetsResponses200, errors={400: ('CreatePresetsResponses400', CreatePresetsResponses400), 401: ('CreatePresetsResponses401', CreatePresetsResponses401), 403: ('CreatePresetsResponses403', CreatePresetsResponses403), 404: ('CreatePresetsResponses404', CreatePresetsResponses404), 409: ('CreatePresetsResponses409', CreatePresetsResponses409), 500: ('CreatePresetsResponses500', CreatePresetsResponses500)})
_RESTORE_PRESET = _c.Operation("POST", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=RestorePreset200, errors={400: ('RestorePreset400', RestorePreset400), 401: ('RestorePreset401', RestorePreset401), 403: ('RestorePreset403', RestorePreset403), 404: ('RestorePreset404', RestorePreset404), 409: ('RestorePreset409', RestorePreset409), 500: ('RestorePreset500', RestorePreset500)})
_LIST_PRESET_VERSIONS = _c.Operation("GET", url_params=('offset', 'limit', 'workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListPresetVersions200, errors={400: ('ListPresetVersions400', ListPresetVersions400), 401: ('ListPresetVersions401', ListPresetVersions401), 403: ('ListPresetVersions403', ListPresetVersions403), 404: ('ListPresetVersions404', ListPresetVersions404), 500: ('ListPresetVersions500', ListPresetVersions500), 503: ('ListPresetVersions503', ListPresetVersions503)})
_GET_PRESET_VERSION = _c.Operation("GET", url_params=('workspace_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetPresetVersion200, errors={400: ('GetPresetVersion400', GetPresetVersion400), 401: ('GetPresetVersion401', GetPresetVersion401), 403: ('GetPresetVersion403', GetPresetVersion403), 404: ('GetPresetVersion404', GetPresetVersion404), 500: ('GetPresetVersion500', GetPresetVersion500), 503: ('GetPresetVersion503', GetPresetVersion503)})
_LIST_PRIVATE_ENDPOINTS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListPrivateEndpoints200, errors={401: ('ListPrivateEndpoints401', ListPrivateEndpoints401), 403: ('ListPrivateEndpoints403', ListPrivateEndpoints403), 408: ('ListPrivateEndpoints408', ListPrivateEndpoints408), 500: ('ListPrivateEndpoints500', ListPrivateEndpoints500)})
_CREATE_PRIVATE_ENDPOINT = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'idempotency-key', ), success=CreatePrivateEndpoint201, errors={400: ('CreatePrivateEndpoint400', CreatePrivateEndpoint400), 401: ('CreatePrivateEndpoint401', CreatePrivateEndpoint401), 403: ('CreatePrivateEndpoint403', CreatePrivateEndpoint403), 404: ('CreatePrivateEndpoint404', CreatePrivateEndpoint404), 408: ('CreatePrivateEndpoint408', CreatePrivateEndpoint408), 409: ('CreatePrivateEndpoint409', CreatePrivateEndpoint409), 422: ('CreatePrivateEndpoint422', CreatePrivateEndpoint422), 500: ('CreatePrivateEndpoint500', CreatePrivateEndpoint500), 502: ('CreatePrivateEndpoint502', CreatePrivateEndpoint502)})
_GET_PRIVATE_ENDPOINT = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetPrivateEndpoint200, errors={401: ('GetPrivateEndpoint401', GetPrivateEndpoint401), 403: ('GetPrivateEndpoint403', GetPrivateEndpoint403), 404: ('GetPrivateEndpoint404', GetPrivateEndpoint404), 408: ('GetPrivateEndpoint408', GetPrivateEndpoint408), 500: ('GetPrivateEndpoint500', GetPrivateEndpoint500)})
_DELETE_PRIVATE_ENDPOINT = _c.Operation("DELETE", url_params=('draft_only', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeletePrivateEndpoint200, errors={400: ('DeletePrivateEndpoint400', DeletePrivateEndpoint400), 401: ('DeletePrivateEndpoint401', DeletePrivateEndpoint401), 403: ('DeletePrivateEndpoint403', DeletePrivateEndpoint403), 404: ('DeletePrivateEndpoint404', DeletePrivateEndpoint404), 408: ('DeletePrivateEndpoint408', DeletePrivateEndpoint408), 409: ('DeletePrivateEndpoint409', DeletePrivateEndpoint409), 422: ('DeletePrivateEndpoint422', DeletePrivateEndpoint422), 500: ('DeletePrivateEndpoint500', DeletePrivateEndpoint500), 502: ('DeletePrivateEndpoint502', DeletePrivateEndpoint502)})
_UPDATE_PRIVATE_ENDPOINT = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdatePrivateEndpoint200, errors={400: ('UpdatePrivateEndpoint400', UpdatePrivateEndpoint400), 401: ('UpdatePrivateEndpoint401', UpdatePrivateEndpoint401), 403: ('UpdatePrivateEndpoint403', UpdatePrivateEndpoint403), 404: ('UpdatePrivateEndpoint404', UpdatePrivateEndpoint404), 408: ('UpdatePrivateEndpoint408', UpdatePrivateEndpoint408), 409: ('UpdatePrivateEndpoint409', UpdatePrivateEndpoint409), 422: ('UpdatePrivateEndpoint422', UpdatePrivateEndpoint422), 500: ('UpdatePrivateEndpoint500', UpdatePrivateEndpoint500), 502: ('UpdatePrivateEndpoint502', UpdatePrivateEndpoint502)})
_ACTIVATE_PRIVATE_ENDPOINT = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ActivatePrivateEndpoint200, errors={400: ('ActivatePrivateEndpoint400', ActivatePrivateEndpoint400), 401: ('ActivatePrivateEndpoint401', ActivatePrivateEndpoint401), 403: ('ActivatePrivateEndpoint403', ActivatePrivateEndpoint403), 404: ('ActivatePrivateEndpoint404', ActivatePrivateEndpoint404), 408: ('ActivatePrivateEndpoint408', ActivatePrivateEndpoint408), 409: ('ActivatePrivateEndpoint409', ActivatePrivateEndpoint409), 422: ('ActivatePrivateEndpoint422', ActivatePrivateEndpoint422), 500: ('ActivatePrivateEndpoint500', ActivatePrivateEndpoint500), 502: ('ActivatePrivateEndpoint502', ActivatePrivateEndpoint502)})
_DISABLE_PRIVATE_ENDPOINT = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DisablePrivateEndpoint200, errors={400: ('DisablePrivateEndpoint400', DisablePrivateEndpoint400), 401: ('DisablePrivateEndpoint401', DisablePrivateEndpoint401), 403: ('DisablePrivateEndpoint403', DisablePrivateEndpoint403), 404: ('DisablePrivateEndpoint404', DisablePrivateEndpoint404), 408: ('DisablePrivateEndpoint408', DisablePrivateEndpoint408), 409: ('DisablePrivateEndpoint409', DisablePrivateEndpoint409), 422: ('DisablePrivateEndpoint422', DisablePrivateEndpoint422), 500: ('DisablePrivateEndpoint500', DisablePrivateEndpoint500), 502: ('DisablePrivateEndpoint502', DisablePrivateEndpoint502)})
_ENABLE_PRIVATE_ENDPOINT = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=EnablePrivateEndpoint200, errors={400: ('EnablePrivateEndpoint400', EnablePrivateEndpoint400), 401: ('EnablePrivateEndpoint401', EnablePrivateEndpoint401), 403: ('EnablePrivateEndpoint403', EnablePrivateEndpoint403), 404: ('EnablePrivateEndpoint404', EnablePrivateEndpoint404), 408: ('EnablePrivateEndpoint408', EnablePrivateEndpoint408), 409: ('EnablePrivateEndpoint409', EnablePrivateEndpoint409), 422: ('EnablePrivateEndpoint422', EnablePrivateEndpoint422), 500: ('EnablePrivateEndpoint500', EnablePrivateEndpoint500), 502: ('EnablePrivateEndpoint502', EnablePrivateEndpoint502)})
_VALIDATE_PRIVATE_ENDPOINT = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ValidatePrivateEndpoint200, errors={400: ('ValidatePrivateEndpoint400', ValidatePrivateEndpoint400), 401: ('ValidatePrivateEndpoint401', ValidatePrivateEndpoint401), 403: ('ValidatePrivateEndpoint403', ValidatePrivateEndpoint403), 404: ('ValidatePrivateEndpoint404', ValidatePrivateEndpoint404), 408: ('ValidatePrivateEndpoint408', ValidatePrivateEndpoint408), 409: ('ValidatePrivateEndpoint409', ValidatePrivateEndpoint409), 422: ('ValidatePrivateEndpoint422', ValidatePrivateEndpoint422), 500: ('ValidatePrivateEndpoint500', ValidatePrivateEndpoint500), 502: ('ValidatePrivateEndpoint502', ValidatePrivateEndpoint502)})
_LIST_PRIVATE_PROVIDERS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListPrivateProviders200, errors={401: ('ListPrivateProviders401', ListPrivateProviders401), 403: ('ListPrivateProviders403', ListPrivateProviders403), 500: ('ListPrivateProviders500', ListPrivateProviders500)})
_CREATE_PRIVATE_PROVIDER = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreatePrivateProvider201, errors={400: ('CreatePrivateProvider400', CreatePrivateProvider400), 401: ('CreatePrivateProvider401', CreatePrivateProvider401), 403: ('CreatePrivateProvider403', CreatePrivateProvider403), 404: ('CreatePrivateProvider404', CreatePrivateProvider404), 408: ('CreatePrivateProvider408', CreatePrivateProvider408), 409: ('CreatePrivateProvider409', CreatePrivateProvider409), 422: ('CreatePrivateProvider422', CreatePrivateProvider422), 429: ('CreatePrivateProvider429', CreatePrivateProvider429), 500: ('CreatePrivateProvider500', CreatePrivateProvider500), 502: ('CreatePrivateProvider502', CreatePrivateProvider502)})
_GET_PRIVATE_PROVIDER = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetPrivateProvider200, errors={401: ('GetPrivateProvider401', GetPrivateProvider401), 403: ('GetPrivateProvider403', GetPrivateProvider403), 404: ('GetPrivateProvider404', GetPrivateProvider404), 500: ('GetPrivateProvider500', GetPrivateProvider500)})
_DELETE_PRIVATE_PROVIDER = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeletePrivateProvider200, errors={400: ('DeletePrivateProvider400', DeletePrivateProvider400), 401: ('DeletePrivateProvider401', DeletePrivateProvider401), 403: ('DeletePrivateProvider403', DeletePrivateProvider403), 404: ('DeletePrivateProvider404', DeletePrivateProvider404), 408: ('DeletePrivateProvider408', DeletePrivateProvider408), 409: ('DeletePrivateProvider409', DeletePrivateProvider409), 422: ('DeletePrivateProvider422', DeletePrivateProvider422), 429: ('DeletePrivateProvider429', DeletePrivateProvider429), 500: ('DeletePrivateProvider500', DeletePrivateProvider500), 502: ('DeletePrivateProvider502', DeletePrivateProvider502)})
_UPDATE_PRIVATE_PROVIDER = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdatePrivateProvider200, errors={400: ('UpdatePrivateProvider400', UpdatePrivateProvider400), 401: ('UpdatePrivateProvider401', UpdatePrivateProvider401), 403: ('UpdatePrivateProvider403', UpdatePrivateProvider403), 404: ('UpdatePrivateProvider404', UpdatePrivateProvider404), 408: ('UpdatePrivateProvider408', UpdatePrivateProvider408), 409: ('UpdatePrivateProvider409', UpdatePrivateProvider409), 422: ('UpdatePrivateProvider422', UpdatePrivateProvider422), 429: ('UpdatePrivateProvider429', UpdatePrivateProvider429), 500: ('UpdatePrivateProvider500', UpdatePrivateProvider500), 502: ('UpdatePrivateProvider502', UpdatePrivateProvider502)})
_LIST_PROVIDERS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListProviders200, errors={500: ('ListProviders500', ListProviders500)})
_CREATE_RERANK = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateRerank200, errors={400: ('CreateRerank400', CreateRerank400), 401: ('CreateRerank401', CreateRerank401), 402: ('CreateRerank402', CreateRerank402), 403: ('CreateRerank403', CreateRerank403), 404: ('CreateRerank404', CreateRerank404), 413: ('CreateRerank413', CreateRerank413), 429: ('CreateRerank429', CreateRerank429), 500: ('CreateRerank500', CreateRerank500), 502: ('CreateRerank502', CreateRerank502), 503: ('CreateRerank503', CreateRerank503), 524: ('CreateRerank524', CreateRerank524), 529: ('CreateRerank529', CreateRerank529)})
_CREATE_RERANK_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_CREATE_RESPONSES = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ), success=CreateResponses200, errors={400: ('CreateResponses400', CreateResponses400), 401: ('CreateResponses401', CreateResponses401), 402: ('CreateResponses402', CreateResponses402), 403: ('CreateResponses403', CreateResponses403), 404: ('CreateResponses404', CreateResponses404), 408: ('CreateResponses408', CreateResponses408), 413: ('CreateResponses413', CreateResponses413), 422: ('CreateResponses422', CreateResponses422), 429: ('CreateResponses429', CreateResponses429), 500: ('CreateResponses500', CreateResponses500), 502: ('CreateResponses502', CreateResponses502), 503: ('CreateResponses503', CreateResponses503), 524: ('CreateResponses524', CreateResponses524), 529: ('CreateResponses529', CreateResponses529)})
_CREATE_RESPONSES_SSE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', 'X-OpenRouter-Metadata', ))
_LIST_SCIM_GROUP_MAPPINGS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListScimGroupMappings200, errors={401: ('ListScimGroupMappings401', ListScimGroupMappings401), 403: ('ListScimGroupMappings403', ListScimGroupMappings403), 404: ('ListScimGroupMappings404', ListScimGroupMappings404), 500: ('ListScimGroupMappings500', ListScimGroupMappings500)})
_CREATE_SCIM_GROUP_MAPPING = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateScimGroupMapping201, errors={400: ('CreateScimGroupMapping400', CreateScimGroupMapping400), 401: ('CreateScimGroupMapping401', CreateScimGroupMapping401), 403: ('CreateScimGroupMapping403', CreateScimGroupMapping403), 404: ('CreateScimGroupMapping404', CreateScimGroupMapping404), 409: ('CreateScimGroupMapping409', CreateScimGroupMapping409), 500: ('CreateScimGroupMapping500', CreateScimGroupMapping500)})
_GET_SCIM_GROUP_MAPPING = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetScimGroupMapping200, errors={401: ('GetScimGroupMapping401', GetScimGroupMapping401), 403: ('GetScimGroupMapping403', GetScimGroupMapping403), 404: ('GetScimGroupMapping404', GetScimGroupMapping404), 500: ('GetScimGroupMapping500', GetScimGroupMapping500)})
_DELETE_SCIM_GROUP_MAPPING = _c.Operation("DELETE", url_params=('keep_members', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteScimGroupMapping200, errors={400: ('DeleteScimGroupMapping400', DeleteScimGroupMapping400), 401: ('DeleteScimGroupMapping401', DeleteScimGroupMapping401), 403: ('DeleteScimGroupMapping403', DeleteScimGroupMapping403), 404: ('DeleteScimGroupMapping404', DeleteScimGroupMapping404), 500: ('DeleteScimGroupMapping500', DeleteScimGroupMapping500)})
_UPDATE_SCIM_GROUP_MAPPING = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateScimGroupMapping200, errors={400: ('UpdateScimGroupMapping400', UpdateScimGroupMapping400), 401: ('UpdateScimGroupMapping401', UpdateScimGroupMapping401), 403: ('UpdateScimGroupMapping403', UpdateScimGroupMapping403), 404: ('UpdateScimGroupMapping404', UpdateScimGroupMapping404), 500: ('UpdateScimGroupMapping500', UpdateScimGroupMapping500)})
_LIST_SCIM_GROUPS = _c.Operation("GET", url_params=('offset', 'limit', 'display_name', 'external_id', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListScimGroups200, errors={401: ('ListScimGroups401', ListScimGroups401), 403: ('ListScimGroups403', ListScimGroups403), 404: ('ListScimGroups404', ListScimGroups404), 500: ('ListScimGroups500', ListScimGroups500)})
_CREATE_SCIM_SYNC_JOB = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateScimSyncJob202, errors={401: ('CreateScimSyncJob401', CreateScimSyncJob401), 403: ('CreateScimSyncJob403', CreateScimSyncJob403), 404: ('CreateScimSyncJob404', CreateScimSyncJob404), 500: ('CreateScimSyncJob500', CreateScimSyncJob500)})
_GET_SCIM_SYNC_JOB = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetScimSyncJob200, errors={401: ('GetScimSyncJob401', GetScimSyncJob401), 403: ('GetScimSyncJob403', GetScimSyncJob403), 404: ('GetScimSyncJob404', GetScimSyncJob404), 500: ('GetScimSyncJob500', GetScimSyncJob500)})
_CREATE_SYSTEMONE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateSystemone200, errors={400: ('CreateSystemone400', CreateSystemone400), 401: ('CreateSystemone401', CreateSystemone401), 402: ('CreateSystemone402', CreateSystemone402), 403: ('CreateSystemone403', CreateSystemone403), 404: ('CreateSystemone404', CreateSystemone404), 413: ('CreateSystemone413', CreateSystemone413), 429: ('CreateSystemone429', CreateSystemone429), 500: ('CreateSystemone500', CreateSystemone500), 502: ('CreateSystemone502', CreateSystemone502), 503: ('CreateSystemone503', CreateSystemone503), 524: ('CreateSystemone524', CreateSystemone524), 529: ('CreateSystemone529', CreateSystemone529)})
_LIST_TOOLS = _c.Operation("GET", url_params=('offset', 'limit', 'api_format', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListTools200, errors={401: ('ListTools401', ListTools401), 403: ('ListTools403', ListTools403), 404: ('ListTools404', ListTools404), 500: ('ListTools500', ListTools500)})
_GET_TOOL = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), status_success={200: GetTool200}, void=(308, ), errors={401: ('GetTool401', GetTool401), 403: ('GetTool403', GetTool403), 404: ('GetTool404', GetTool404), 500: ('GetTool500', GetTool500)})
_LIST_INTERN_CONNECTIONS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListInternConnections200, errors={400: ('ListInternConnections400', ListInternConnections400), 401: ('ListInternConnections401', ListInternConnections401), 403: ('ListInternConnections403', ListInternConnections403), 404: ('ListInternConnections404', ListInternConnections404), 408: ('ListInternConnections408', ListInternConnections408), 429: ('ListInternConnections429', ListInternConnections429), 500: ('ListInternConnections500', ListInternConnections500), 502: ('ListInternConnections502', ListInternConnections502), 503: ('ListInternConnections503', ListInternConnections503), 504: ('ListInternConnections504', ListInternConnections504)})
_LIST_INTERN_EFFECTIVE_VAULT_SECRETS = _c.Operation("GET", url_params=('limit', 'offset', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListInternEffectiveVaultSecrets200, errors={400: ('ListInternEffectiveVaultSecrets400', ListInternEffectiveVaultSecrets400), 401: ('ListInternEffectiveVaultSecrets401', ListInternEffectiveVaultSecrets401), 403: ('ListInternEffectiveVaultSecrets403', ListInternEffectiveVaultSecrets403), 404: ('ListInternEffectiveVaultSecrets404', ListInternEffectiveVaultSecrets404), 408: ('ListInternEffectiveVaultSecrets408', ListInternEffectiveVaultSecrets408), 429: ('ListInternEffectiveVaultSecrets429', ListInternEffectiveVaultSecrets429), 500: ('ListInternEffectiveVaultSecrets500', ListInternEffectiveVaultSecrets500), 502: ('ListInternEffectiveVaultSecrets502', ListInternEffectiveVaultSecrets502), 503: ('ListInternEffectiveVaultSecrets503', ListInternEffectiveVaultSecrets503), 504: ('ListInternEffectiveVaultSecrets504', ListInternEffectiveVaultSecrets504)})
_LIST_INTERN_VAULT_SECRETS = _c.Operation("GET", url_params=('limit', 'offset', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListInternVaultSecrets200, errors={400: ('ListInternVaultSecrets400', ListInternVaultSecrets400), 401: ('ListInternVaultSecrets401', ListInternVaultSecrets401), 403: ('ListInternVaultSecrets403', ListInternVaultSecrets403), 404: ('ListInternVaultSecrets404', ListInternVaultSecrets404), 408: ('ListInternVaultSecrets408', ListInternVaultSecrets408), 429: ('ListInternVaultSecrets429', ListInternVaultSecrets429), 500: ('ListInternVaultSecrets500', ListInternVaultSecrets500), 502: ('ListInternVaultSecrets502', ListInternVaultSecrets502), 503: ('ListInternVaultSecrets503', ListInternVaultSecrets503), 504: ('ListInternVaultSecrets504', ListInternVaultSecrets504)})
_STORE_INTERN_VAULT_SECRET = _c.Operation("PUT", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=StoreInternVaultSecret200, errors={400: ('StoreInternVaultSecret400', StoreInternVaultSecret400), 401: ('StoreInternVaultSecret401', StoreInternVaultSecret401), 403: ('StoreInternVaultSecret403', StoreInternVaultSecret403), 404: ('StoreInternVaultSecret404', StoreInternVaultSecret404), 408: ('StoreInternVaultSecret408', StoreInternVaultSecret408), 409: ('StoreInternVaultSecret409', StoreInternVaultSecret409), 413: ('StoreInternVaultSecret413', StoreInternVaultSecret413), 429: ('StoreInternVaultSecret429', StoreInternVaultSecret429), 500: ('StoreInternVaultSecret500', StoreInternVaultSecret500), 502: ('StoreInternVaultSecret502', StoreInternVaultSecret502), 503: ('StoreInternVaultSecret503', StoreInternVaultSecret503), 504: ('StoreInternVaultSecret504', StoreInternVaultSecret504)})
_DELETE_INTERN_VAULT_SECRET = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), void=(204, ), errors={400: ('DeleteInternVaultSecret400', DeleteInternVaultSecret400), 401: ('DeleteInternVaultSecret401', DeleteInternVaultSecret401), 403: ('DeleteInternVaultSecret403', DeleteInternVaultSecret403), 404: ('DeleteInternVaultSecret404', DeleteInternVaultSecret404), 408: ('DeleteInternVaultSecret408', DeleteInternVaultSecret408), 409: ('DeleteInternVaultSecret409', DeleteInternVaultSecret409), 429: ('DeleteInternVaultSecret429', DeleteInternVaultSecret429), 500: ('DeleteInternVaultSecret500', DeleteInternVaultSecret500), 502: ('DeleteInternVaultSecret502', DeleteInternVaultSecret502), 503: ('DeleteInternVaultSecret503', DeleteInternVaultSecret503), 504: ('DeleteInternVaultSecret504', DeleteInternVaultSecret504)})
_COPY_VAULT_SECRETS_TO_INTERN = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CopyVaultSecretsToIntern200, errors={400: ('CopyVaultSecretsToIntern400', CopyVaultSecretsToIntern400), 401: ('CopyVaultSecretsToIntern401', CopyVaultSecretsToIntern401), 403: ('CopyVaultSecretsToIntern403', CopyVaultSecretsToIntern403), 404: ('CopyVaultSecretsToIntern404', CopyVaultSecretsToIntern404), 408: ('CopyVaultSecretsToIntern408', CopyVaultSecretsToIntern408), 409: ('CopyVaultSecretsToIntern409', CopyVaultSecretsToIntern409), 413: ('CopyVaultSecretsToIntern413', CopyVaultSecretsToIntern413), 429: ('CopyVaultSecretsToIntern429', CopyVaultSecretsToIntern429), 500: ('CopyVaultSecretsToIntern500', CopyVaultSecretsToIntern500), 502: ('CopyVaultSecretsToIntern502', CopyVaultSecretsToIntern502), 503: ('CopyVaultSecretsToIntern503', CopyVaultSecretsToIntern503), 504: ('CopyVaultSecretsToIntern504', CopyVaultSecretsToIntern504)})
_LIST_VAULT_SECRETS = _c.Operation("GET", url_params=('limit', 'offset', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListVaultSecrets200, errors={400: ('ListVaultSecrets400', ListVaultSecrets400), 401: ('ListVaultSecrets401', ListVaultSecrets401), 403: ('ListVaultSecrets403', ListVaultSecrets403), 404: ('ListVaultSecrets404', ListVaultSecrets404), 408: ('ListVaultSecrets408', ListVaultSecrets408), 429: ('ListVaultSecrets429', ListVaultSecrets429), 500: ('ListVaultSecrets500', ListVaultSecrets500), 502: ('ListVaultSecrets502', ListVaultSecrets502), 503: ('ListVaultSecrets503', ListVaultSecrets503), 504: ('ListVaultSecrets504', ListVaultSecrets504)})
_STORE_VAULT_SECRET = _c.Operation("PUT", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=StoreVaultSecret200, errors={400: ('StoreVaultSecret400', StoreVaultSecret400), 401: ('StoreVaultSecret401', StoreVaultSecret401), 403: ('StoreVaultSecret403', StoreVaultSecret403), 404: ('StoreVaultSecret404', StoreVaultSecret404), 408: ('StoreVaultSecret408', StoreVaultSecret408), 409: ('StoreVaultSecret409', StoreVaultSecret409), 413: ('StoreVaultSecret413', StoreVaultSecret413), 429: ('StoreVaultSecret429', StoreVaultSecret429), 500: ('StoreVaultSecret500', StoreVaultSecret500), 502: ('StoreVaultSecret502', StoreVaultSecret502), 503: ('StoreVaultSecret503', StoreVaultSecret503), 504: ('StoreVaultSecret504', StoreVaultSecret504)})
_DELETE_VAULT_SECRET = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), void=(204, ), errors={400: ('DeleteVaultSecret400', DeleteVaultSecret400), 401: ('DeleteVaultSecret401', DeleteVaultSecret401), 403: ('DeleteVaultSecret403', DeleteVaultSecret403), 404: ('DeleteVaultSecret404', DeleteVaultSecret404), 408: ('DeleteVaultSecret408', DeleteVaultSecret408), 409: ('DeleteVaultSecret409', DeleteVaultSecret409), 429: ('DeleteVaultSecret429', DeleteVaultSecret429), 500: ('DeleteVaultSecret500', DeleteVaultSecret500), 502: ('DeleteVaultSecret502', DeleteVaultSecret502), 503: ('DeleteVaultSecret503', DeleteVaultSecret503), 504: ('DeleteVaultSecret504', DeleteVaultSecret504)})
_CREATE_VIDEOS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateVideos202, errors={400: ('CreateVideos400', CreateVideos400), 401: ('CreateVideos401', CreateVideos401), 402: ('CreateVideos402', CreateVideos402), 403: ('CreateVideos403', CreateVideos403), 404: ('CreateVideos404', CreateVideos404), 413: ('CreateVideos413', CreateVideos413), 429: ('CreateVideos429', CreateVideos429), 499: ('CreateVideos499', CreateVideos499), 500: ('CreateVideos500', CreateVideos500), 503: ('CreateVideos503', CreateVideos503)})
_GET_VIDEOS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetVideos200, errors={401: ('GetVideos401', GetVideos401), 403: ('GetVideos403', GetVideos403), 404: ('GetVideos404', GetVideos404), 500: ('GetVideos500', GetVideos500)})
_LIST_VIDEOS_CONTENT = _c.Operation("GET", url_params=('index', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), binary_success=True, errors={400: ('ListVideosContent400', ListVideosContent400), 401: ('ListVideosContent401', ListVideosContent401), 403: ('ListVideosContent403', ListVideosContent403), 404: ('ListVideosContent404', ListVideosContent404), 409: ('ListVideosContent409', ListVideosContent409), 410: ('ListVideosContent410', ListVideosContent410), 500: ('ListVideosContent500', ListVideosContent500), 502: ('ListVideosContent502', ListVideosContent502)})
_LIST_VIDEOS_CONTENT_STREAM = _c.Operation("GET", url_params=('index', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ))
_LIST_VIDEOS_MODELS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListVideosModels200, errors={400: ('ListVideosModels400', ListVideosModels400), 500: ('ListVideosModels500', ListVideosModels500)})
_LIST_WORKSPACES = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListWorkspaces200, errors={401: ('ListWorkspaces401', ListWorkspaces401), 403: ('ListWorkspaces403', ListWorkspaces403), 500: ('ListWorkspaces500', ListWorkspaces500)})
_CREATE_WORKSPACE = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=CreateWorkspace201, errors={400: ('CreateWorkspace400', CreateWorkspace400), 401: ('CreateWorkspace401', CreateWorkspace401), 403: ('CreateWorkspace403', CreateWorkspace403), 500: ('CreateWorkspace500', CreateWorkspace500)})
_GET_WORKSPACE = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetWorkspace200, errors={401: ('GetWorkspace401', GetWorkspace401), 403: ('GetWorkspace403', GetWorkspace403), 404: ('GetWorkspace404', GetWorkspace404), 500: ('GetWorkspace500', GetWorkspace500)})
_DELETE_WORKSPACE = _c.Operation("DELETE", url_params=('confirm_default_workspace_deletion', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteWorkspace200, errors={400: ('DeleteWorkspace400', DeleteWorkspace400), 401: ('DeleteWorkspace401', DeleteWorkspace401), 403: ('DeleteWorkspace403', DeleteWorkspace403), 404: ('DeleteWorkspace404', DeleteWorkspace404), 500: ('DeleteWorkspace500', DeleteWorkspace500)})
_UPDATE_WORKSPACE = _c.Operation("PATCH", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpdateWorkspace200, errors={400: ('UpdateWorkspace400', UpdateWorkspace400), 401: ('UpdateWorkspace401', UpdateWorkspace401), 403: ('UpdateWorkspace403', UpdateWorkspace403), 404: ('UpdateWorkspace404', UpdateWorkspace404), 500: ('UpdateWorkspace500', UpdateWorkspace500)})
_LIST_WORKSPACE_MEMBERS = _c.Operation("GET", url_params=('offset', 'limit', ), headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListWorkspaceMembers200, errors={401: ('ListWorkspaceMembers401', ListWorkspaceMembers401), 403: ('ListWorkspaceMembers403', ListWorkspaceMembers403), 404: ('ListWorkspaceMembers404', ListWorkspaceMembers404), 500: ('ListWorkspaceMembers500', ListWorkspaceMembers500)})
_BULK_ADD_WORKSPACE_MEMBERS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkAddWorkspaceMembers200, errors={400: ('BulkAddWorkspaceMembers400', BulkAddWorkspaceMembers400), 401: ('BulkAddWorkspaceMembers401', BulkAddWorkspaceMembers401), 403: ('BulkAddWorkspaceMembers403', BulkAddWorkspaceMembers403), 404: ('BulkAddWorkspaceMembers404', BulkAddWorkspaceMembers404), 500: ('BulkAddWorkspaceMembers500', BulkAddWorkspaceMembers500)})
_BULK_REMOVE_WORKSPACE_MEMBERS = _c.Operation("POST", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=BulkRemoveWorkspaceMembers200, errors={400: ('BulkRemoveWorkspaceMembers400', BulkRemoveWorkspaceMembers400), 401: ('BulkRemoveWorkspaceMembers401', BulkRemoveWorkspaceMembers401), 403: ('BulkRemoveWorkspaceMembers403', BulkRemoveWorkspaceMembers403), 404: ('BulkRemoveWorkspaceMembers404', BulkRemoveWorkspaceMembers404), 500: ('BulkRemoveWorkspaceMembers500', BulkRemoveWorkspaceMembers500)})
_LIST_WORKSPACE_BUDGETS = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=ListWorkspaceBudgets200, errors={401: ('ListWorkspaceBudgets401', ListWorkspaceBudgets401), 403: ('ListWorkspaceBudgets403', ListWorkspaceBudgets403), 404: ('ListWorkspaceBudgets404', ListWorkspaceBudgets404), 500: ('ListWorkspaceBudgets500', ListWorkspaceBudgets500)})
_GET_WORKSPACE_BUDGET = _c.Operation("GET", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=GetWorkspaceBudget200, errors={400: ('GetWorkspaceBudget400', GetWorkspaceBudget400), 401: ('GetWorkspaceBudget401', GetWorkspaceBudget401), 403: ('GetWorkspaceBudget403', GetWorkspaceBudget403), 404: ('GetWorkspaceBudget404', GetWorkspaceBudget404), 500: ('GetWorkspaceBudget500', GetWorkspaceBudget500)})
_UPSERT_WORKSPACE_BUDGET = _c.Operation("PUT", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=UpsertWorkspaceBudget200, errors={400: ('UpsertWorkspaceBudget400', UpsertWorkspaceBudget400), 401: ('UpsertWorkspaceBudget401', UpsertWorkspaceBudget401), 403: ('UpsertWorkspaceBudget403', UpsertWorkspaceBudget403), 404: ('UpsertWorkspaceBudget404', UpsertWorkspaceBudget404), 500: ('UpsertWorkspaceBudget500', UpsertWorkspaceBudget500)})
_DELETE_WORKSPACE_BUDGET = _c.Operation("DELETE", headers=('HTTP-Referer', 'X-OpenRouter-Title', 'X-OpenRouter-Categories', ), success=DeleteWorkspaceBudget200, errors={400: ('DeleteWorkspaceBudget400', DeleteWorkspaceBudget400), 401: ('DeleteWorkspaceBudget401', DeleteWorkspaceBudget401), 403: ('DeleteWorkspaceBudget403', DeleteWorkspaceBudget403), 404: ('DeleteWorkspaceBudget404', DeleteWorkspaceBudget404), 500: ('DeleteWorkspaceBudget500', DeleteWorkspaceBudget500)})


class OpenRouterClient(_c.GeneratedClient):
    """The OpenRouter API: build it with ``make``."""

    __slots__ = ()

    error_class = OpenRouterClientError
    transform_streams = True

    @_t.overload
    def get_user_activity(self, *, params: _T.GetUserActivityParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetUserActivity200, _Errors]: ...
    @_t.overload
    def get_user_activity(self, *, params: _T.GetUserActivityParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetUserActivity200, _HttpClientResponse], _Errors]: ...
    def get_user_activity(self, *, params: _T.GetUserActivityParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns user activity data grouped by endpoint for the last 30 (completed) UTC days. Pass `workspace_id` to scope the response to a single workspace. Pass `group_by=workspace` to split each row per workspace and include `workspace_id` on every item; by default rows are aggregated across workspaces and `workspace_id` is not returned. Activity recorded before workspace resolution existed is permanently attributed to the account default workspace (no backfill is possible). [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_USER_ACTIVITY, "/activity", params, None, include_response)

    @_t.overload
    def get_analytics_meta(self, *, params: _T.GetAnalyticsMetaParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetAnalyticsMeta200, _Errors]: ...
    @_t.overload
    def get_analytics_meta(self, *, params: _T.GetAnalyticsMetaParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetAnalyticsMeta200, _HttpClientResponse], _Errors]: ...
    def get_analytics_meta(self, *, params: _T.GetAnalyticsMetaParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns the available metrics, dimensions, filter operators, and granularities for the analytics query endpoint. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_ANALYTICS_META, "/analytics/meta", params, None, include_response)

    @_t.overload
    def query_analytics(self, *, payload: _T.QueryAnalyticsRequestJson, params: _T.QueryAnalyticsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.QueryAnalytics200, _Errors]: ...
    @_t.overload
    def query_analytics(self, *, payload: _T.QueryAnalyticsRequestJson, params: _T.QueryAnalyticsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.QueryAnalytics200, _HttpClientResponse], _Errors]: ...
    def query_analytics(self, *, payload: _T.QueryAnalyticsRequestJson, params: _T.QueryAnalyticsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Execute an analytics query with specified metrics, dimensions, filters, and time range. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_QUERY_ANALYTICS, "/analytics/query", params, _c.json_body(payload), include_response)

    @_t.overload
    def create_api_alpha_decisions(self, *, payload: _T.CreateApiAlphaDecisionsRequestJson, params: _T.CreateApiAlphaDecisionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateApiAlphaDecisions200, _Errors]: ...
    @_t.overload
    def create_api_alpha_decisions(self, *, payload: _T.CreateApiAlphaDecisionsRequestJson, params: _T.CreateApiAlphaDecisionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateApiAlphaDecisions200, _HttpClientResponse], _Errors]: ...
    def create_api_alpha_decisions(self, *, payload: _T.CreateApiAlphaDecisionsRequestJson, params: _T.CreateApiAlphaDecisionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Asks a Decisions model typed questions (`noul`, `choice`, `score`, `box`) about the content in `state` and returns one typed answer per question with its probabilities. Images, audio and video go in `state` as `image_url`, `input_audio` and `video_url` parts; PNG and JPEG images can instead go once in `assets` and be referenced by key. Which question types, media parts and asset references an endpoint accepts depends on the provider; a request an endpoint cannot serve fails with `400` before anything is sent upstream. See the [Multimodal Decisions guide](https://openrouter.ai/docs/guides/community/multimodal-decisions) for the per-provider table. Typed fields (text, numbers, dates, lists, estimates, forecasts) come from [`POST /api/alpha/extractions`](https://openrouter.ai/docs/guides/community/extractions), which takes the same envelope with `fields` in place of `questions` (text `state` only; images and PDFs go in `assets`). Alpha: the shape may change."""
        return self._json(_CREATE_API_ALPHA_DECISIONS, "/api/alpha/decisions", params, _c.json_body(payload), include_response)

    @_t.overload
    def create_api_alpha_extractions(self, *, payload: _T.CreateApiAlphaExtractionsRequestJson, params: _T.CreateApiAlphaExtractionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateApiAlphaExtractions200, _Errors]: ...
    @_t.overload
    def create_api_alpha_extractions(self, *, payload: _T.CreateApiAlphaExtractionsRequestJson, params: _T.CreateApiAlphaExtractionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateApiAlphaExtractions200, _HttpClientResponse], _Errors]: ...
    def create_api_alpha_extractions(self, *, payload: _T.CreateApiAlphaExtractionsRequestJson, params: _T.CreateApiAlphaExtractionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Extracts, computes, estimates or forecasts typed fields from a state string and image assets using an extraction-style System One model. Alpha: the shape is not stable."""
        return self._json(_CREATE_API_ALPHA_EXTRACTIONS, "/api/alpha/extractions", params, _c.json_body(payload), include_response)

    @_t.overload
    def create_audio_speech(self, *, payload: _T.CreateAudioSpeechRequestJson, params: _T.CreateAudioSpeechParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def create_audio_speech(self, *, payload: _T.CreateAudioSpeechRequestJson, params: _T.CreateAudioSpeechParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def create_audio_speech(self, *, payload: _T.CreateAudioSpeechRequestJson, params: _T.CreateAudioSpeechParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Synthesizes audio from the input text. Returns a raw audio bytestream in the requested format (e.g. mp3, pcm, wav)."""
        return self._json(_CREATE_AUDIO_SPEECH, "/audio/speech", params, _c.json_body(payload), include_response)

    def create_audio_speech_stream(self, *, payload: _T.CreateAudioSpeechRequestJson, params: _T.CreateAudioSpeechParams | None = None) -> _Stream[bytes, _HttpClientError]:
        """Synthesizes audio from the input text. Returns a raw audio bytestream in the requested format (e.g. mp3, pcm, wav)."""
        return self._binary(_CREATE_AUDIO_SPEECH_STREAM, "/audio/speech", params, _c.json_body(payload))

    @_t.overload
    def create_audio_transcriptions(self, *, payload: _T.CreateAudioTranscriptionsRequestJson, params: _T.CreateAudioTranscriptionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateAudioTranscriptions200, _Errors]: ...
    @_t.overload
    def create_audio_transcriptions(self, *, payload: _T.CreateAudioTranscriptionsRequestJson, params: _T.CreateAudioTranscriptionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateAudioTranscriptions200, _HttpClientResponse], _Errors]: ...
    def create_audio_transcriptions(self, *, payload: _T.CreateAudioTranscriptionsRequestJson, params: _T.CreateAudioTranscriptionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Transcribes audio into text. Accepts base64-encoded audio input as JSON, an OpenAI-style multipart/form-data file upload, or a URL the provider downloads directly, and returns the transcribed text."""
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
    def list_batches(self, *, params: _T.ListBatchesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListBatches200, _Errors]: ...
    @_t.overload
    def list_batches(self, *, params: _T.ListBatchesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListBatches200, _HttpClientResponse], _Errors]: ...
    def list_batches(self, *, params: _T.ListBatchesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists batches in the workspace of the authenticating API key, newest first. To fetch the next page, pass the previous page's `last_id` as `after`. List items omit `results`. Use `GET /batches/{id}` to get them. See the [Batch API Quickstart](https://openrouter.ai/docs/batch-quickstart)."""
        return self._json(_LIST_BATCHES, "/batches", params, None, include_response)

    @_t.overload
    def create_batches(self, *, payload: _T.CreateBatchesRequestJson, params: _T.CreateBatchesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateBatches202, _Errors]: ...
    @_t.overload
    def create_batches(self, *, payload: _T.CreateBatchesRequestJson, params: _T.CreateBatchesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateBatches202, _HttpClientResponse], _Errors]: ...
    def create_batches(self, *, payload: _T.CreateBatchesRequestJson, params: _T.CreateBatchesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a batch of requests that run asynchronously against a single endpoint (`/v1/chat/completions`, `/v1/responses`, `/v1/messages`, `/v1/embeddings`). Returns `202` with `status: "validating"`. Poll `GET /batches/{id}` for progress and results. See the [Batch API Quickstart](https://openrouter.ai/docs/batch-quickstart)."""
        return self._json(_CREATE_BATCHES, "/batches", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_batches(self, id: str, *, params: _T.GetBatchesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetBatches200, _Errors]: ...
    @_t.overload
    def get_batches(self, id: str, *, params: _T.GetBatchesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetBatches200, _HttpClientResponse], _Errors]: ...
    def get_batches(self, id: str, *, params: _T.GetBatchesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a batch with its status and request counts. Batches in a terminal status include `results`. Failed batches report the reason in `error.message`. See the [Batch API Quickstart](https://openrouter.ai/docs/batch-quickstart)."""
        return self._json(_GET_BATCHES, _c.encoded_path("/batches/{}", id), params, None, include_response)

    @_t.overload
    def delete_batch(self, id: str, *, params: _T.DeleteBatchParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteBatch200, _Errors]: ...
    @_t.overload
    def delete_batch(self, id: str, *, params: _T.DeleteBatchParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteBatch200, _HttpClientResponse], _Errors]: ...
    def delete_batch(self, id: str, *, params: _T.DeleteBatchParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a batch in a terminal status (`completed`, `failed`, `expired`, or `cancelled`) and its stored requests and results. Batches still in progress return `409`. Billing and usage records are kept. See the [Batch API Quickstart](https://openrouter.ai/docs/batch-quickstart)."""
        return self._json(_DELETE_BATCH, _c.encoded_path("/batches/{}", id), params, None, include_response)

    @_t.overload
    def get_benchmarks(self, *, params: _T.GetBenchmarksParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetBenchmarks200, _Errors]: ...
    @_t.overload
    def get_benchmarks(self, *, params: _T.GetBenchmarksParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetBenchmarks200, _HttpClientResponse], _Errors]: ...
    def get_benchmarks(self, *, params: _T.GetBenchmarksParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Unified benchmark endpoint that aggregates scores from multiple benchmark sources (Artificial Analysis, Design Arena, and OpenRouter's own tau-bench, GPQA, and web-search evals). Filter by source to reproduce the exact shapes from the legacy per-source endpoints, or use task_type to find models suited for specific workloads. Use task_type=search (or a search_* benchmark_type) for OpenRouter's search benchmarks, which publish each model's highest-scoring eligible evaluation configuration with same-configuration runs combined by task-weighted mean. Authenticate with any valid OpenRouter API key. Rate-limited to 30 requests/minute per key and 500 requests/day per account."""
        return self._json(_GET_BENCHMARKS, "/benchmarks", params, None, include_response)

    @_t.overload
    def list_byok_keys(self, *, params: _T.ListBYOKKeysParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListBYOKKeys200, _Errors]: ...
    @_t.overload
    def list_byok_keys(self, *, params: _T.ListBYOKKeysParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListBYOKKeys200, _HttpClientResponse], _Errors]: ...
    def list_byok_keys(self, *, params: _T.ListBYOKKeysParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the bring-your-own-key (BYOK) provider credentials for the authenticated entity's default workspace. Use the `workspace_id` query parameter to scope the result to a different workspace, or the `provider` query parameter to filter by upstream provider. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_BYOK_KEYS, "/byok", params, None, include_response)

    @_t.overload
    def create_byok_key(self, *, payload: _T.CreateBYOKKeyRequestJson, params: _T.CreateBYOKKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateBYOKKey201, _Errors]: ...
    @_t.overload
    def create_byok_key(self, *, payload: _T.CreateBYOKKeyRequestJson, params: _T.CreateBYOKKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateBYOKKey201, _HttpClientResponse], _Errors]: ...
    def create_byok_key(self, *, payload: _T.CreateBYOKKeyRequestJson, params: _T.CreateBYOKKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new bring-your-own-key (BYOK) provider credential. The raw key is encrypted at rest and never returned in API responses. When `workspace_id` is omitted, the credential is created in the default workspace; if that default has been deleted, the request returns a 400 and you must pass `workspace_id` explicitly. Treat the raw key as write-only; it is never returned after creation. Use `allowed_api_key_hashes` to restrict the credential to specific OpenRouter API keys. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_BYOK_KEY, "/byok", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_byok_key(self, id: str, *, params: _T.GetBYOKKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetBYOKKey200, _Errors]: ...
    @_t.overload
    def get_byok_key(self, id: str, *, params: _T.GetBYOKKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetBYOKKey200, _HttpClientResponse], _Errors]: ...
    def get_byok_key(self, id: str, *, params: _T.GetBYOKKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a single bring-your-own-key (BYOK) provider credential by its `id`. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_BYOK_KEY, _c.encoded_path("/byok/{}", id), params, None, include_response)

    @_t.overload
    def delete_byok_key(self, id: str, *, params: _T.DeleteBYOKKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteBYOKKey200, _Errors]: ...
    @_t.overload
    def delete_byok_key(self, id: str, *, params: _T.DeleteBYOKKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteBYOKKey200, _HttpClientResponse], _Errors]: ...
    def delete_byok_key(self, id: str, *, params: _T.DeleteBYOKKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete (soft-delete) a bring-your-own-key (BYOK) provider credential by its `id`. The encrypted key material is wiped and the record is marked as deleted. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_BYOK_KEY, _c.encoded_path("/byok/{}", id), params, None, include_response)

    @_t.overload
    def update_byok_key(self, id: str, *, payload: _T.UpdateBYOKKeyRequestJson, params: _T.UpdateBYOKKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateBYOKKey200, _Errors]: ...
    @_t.overload
    def update_byok_key(self, id: str, *, payload: _T.UpdateBYOKKeyRequestJson, params: _T.UpdateBYOKKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateBYOKKey200, _HttpClientResponse], _Errors]: ...
    def update_byok_key(self, id: str, *, payload: _T.UpdateBYOKKeyRequestJson, params: _T.UpdateBYOKKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update an existing bring-your-own-key (BYOK) provider credential by its `id`. Include the `key` field to rotate the raw provider API key in-place (the previous key material is overwritten). Use `allowed_api_key_hashes` to restrict the credential to specific OpenRouter API keys (`null` clears the restriction). [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_BYOK_KEY, _c.encoded_path("/byok/{}", id), params, _c.json_body(payload), include_response)

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
    def list_container_files(self, container_id: str, *, params: _T.ListContainerFilesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListContainerFiles200, _Errors]: ...
    @_t.overload
    def list_container_files(self, container_id: str, *, params: _T.ListContainerFilesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListContainerFiles200, _HttpClientResponse], _Errors]: ...
    def list_container_files(self, container_id: str, *, params: _T.ListContainerFilesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the files in a container, in lexicographic path order. The container id is the canonical id returned in bash/shell tool results; a restarted session is a separate container with its own id. Paginate with `limit` and `after` (pass the previous page’s `last_id`); `has_more: true` always means the next page is fetchable that way. `last_id` is the resume cursor: it is the last listed file’s id, except when a page ends at the per-request scan bound on hidden bookkeeping objects, where it names the scan position instead and may not appear in `data` (which can then be empty)."""
        return self._json(_LIST_CONTAINER_FILES, _c.encoded_path("/containers/{}/files", container_id), params, None, include_response)

    @_t.overload
    def get_container_file(self, container_id: str, file_id: str, *, params: _T.GetContainerFileParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetContainerFile200, _Errors]: ...
    @_t.overload
    def get_container_file(self, container_id: str, file_id: str, *, params: _T.GetContainerFileParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetContainerFile200, _HttpClientResponse], _Errors]: ...
    def get_container_file(self, container_id: str, file_id: str, *, params: _T.GetContainerFileParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns the metadata of a single file in a container."""
        return self._json(_GET_CONTAINER_FILE, _c.encoded_path("/containers/{}/files/{}", container_id, file_id), params, None, include_response)

    @_t.overload
    def download_container_file_content(self, container_id: str, file_id: str, *, params: _T.DownloadContainerFileContentParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def download_container_file_content(self, container_id: str, file_id: str, *, params: _T.DownloadContainerFileContentParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def download_container_file_content(self, container_id: str, file_id: str, *, params: _T.DownloadContainerFileContentParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Streams the raw bytes of a file in a container."""
        return self._json(_DOWNLOAD_CONTAINER_FILE_CONTENT, _c.encoded_path("/containers/{}/files/{}/content", container_id, file_id), params, None, include_response)

    def download_container_file_content_stream(self, container_id: str, file_id: str, *, params: _T.DownloadContainerFileContentParams | None = None) -> _Stream[bytes, _HttpClientError]:
        """Streams the raw bytes of a file in a container."""
        return self._binary(_DOWNLOAD_CONTAINER_FILE_CONTENT_STREAM, _c.encoded_path("/containers/{}/files/{}/content", container_id, file_id), params, None)

    @_t.overload
    def promote_container_file(self, container_id: str, file_id: str, *, params: _T.PromoteContainerFileParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.PromoteContainerFile200, _Errors]: ...
    @_t.overload
    def promote_container_file(self, container_id: str, file_id: str, *, params: _T.PromoteContainerFileParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.PromoteContainerFile200, _HttpClientResponse], _Errors]: ...
    def promote_container_file(self, container_id: str, file_id: str, *, params: _T.PromoteContainerFileParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Copies a file from the container's sandbox prefix into the workspace's durable document storage, so it outlives the container. Returns the new document in the Files API shape, with a durable file id in the documents namespace. The copy counts against the workspace's storage quota. Unlike a direct upload, promoted files are downloadable."""
        return self._json(_PROMOTE_CONTAINER_FILE, _c.encoded_path("/containers/{}/files/{}/promote", container_id, file_id), params, None, include_response)

    @_t.overload
    def get_credits(self, *, params: _T.GetCreditsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetCredits200, _Errors]: ...
    @_t.overload
    def get_credits(self, *, params: _T.GetCreditsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetCredits200, _HttpClientResponse], _Errors]: ...
    def get_credits(self, *, params: _T.GetCreditsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get total credits purchased and used for the authenticated user. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_CREDITS, "/credits", params, None, include_response)

    @_t.overload
    def create_coinbase_charge(self, *, params: _T.CreateCoinbaseChargeParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def create_coinbase_charge(self, *, params: _T.CreateCoinbaseChargeParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def create_coinbase_charge(self, *, params: _T.CreateCoinbaseChargeParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deprecated. The Coinbase APIs used by this endpoint have been deprecated, so Coinbase Commerce charges have been removed. Use the web credits purchase flow instead."""
        return self._json(_CREATE_COINBASE_CHARGE, "/credits/coinbase", params, None, include_response)

    @_t.overload
    def create_credits_purchases(self, *, payload: _T.CreateCreditsPurchasesRequestJson, params: _T.CreateCreditsPurchasesParams, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateCreditsPurchases202, _Errors]: ...
    @_t.overload
    def create_credits_purchases(self, *, payload: _T.CreateCreditsPurchasesRequestJson, params: _T.CreateCreditsPurchasesParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateCreditsPurchases202, _HttpClientResponse], _Errors]: ...
    def create_credits_purchases(self, *, payload: _T.CreateCreditsPurchasesRequestJson, params: _T.CreateCreditsPurchasesParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Starts an agent credit purchase paid with a Machine Payments Protocol (MPP) credential on Tempo. The first call answers `402` with a `WWW-Authenticate: Payment ...` challenge; retry the same request, same `Idempotency-Key`, with the signed credential in `Payment-Authorization: Payment ...` (or in `Authorization: Payment ...` when the management key is sent as `X-Api-Key`). A paid request answers `202`: the transfer was broadcast and Stripe is still screening the payment, so credits arrive asynchronously. Poll the URL in the `Location` header, `GET /api/v1/credits/purchases/{id}`, until `status` is `credited` or `failed`."""
        return self._json(_CREATE_CREDITS_PURCHASES, "/credits/purchases", params, _c.json_body(payload), include_response)

    @_t.overload
    def list_credits_purchases(self, id: str, *, params: _T.ListCreditsPurchasesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListCreditsPurchases200, _Errors]: ...
    @_t.overload
    def list_credits_purchases(self, id: str, *, params: _T.ListCreditsPurchasesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListCreditsPurchases200, _HttpClientResponse], _Errors]: ...
    def list_credits_purchases(self, id: str, *, params: _T.ListCreditsPurchasesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns one agent credit purchase of the calling account, read from its Stripe PaymentIntent. Poll this after a `202` until `status` is `credited` or `failed`."""
        return self._json(_LIST_CREDITS_PURCHASES, _c.encoded_path("/credits/purchases/{}", id), params, None, include_response)

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
        traffic flows through a different provider.
        
        Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): reuse and republish with attribution to OpenRouter."""
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
        different provider.
        
        Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): reuse and republish with attribution to OpenRouter."""
        return self._json(_GET_RANKINGS_DAILY, "/datasets/rankings-daily", params, None, include_response)

    @_t.overload
    def get_session_cost(self, *, params: _T.GetSessionCostParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetSessionCost200, _Errors]: ...
    @_t.overload
    def get_session_cost(self, *, params: _T.GetSessionCostParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetSessionCost200, _HttpClientResponse], _Errors]: ...
    def get_session_cost(self, *, params: _T.GetSessionCostParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns weekly refreshed, aggregated cost-per-session cells for the published harnesses.
        Sessions are never pooled across apps. Medians are of per-session USD spend, and
        privacy-preserving aggregation never exposes clerk_user_id values or per-session rows.
        
        Filter by `app_slug`, `model`, or `turn_range`. Filtering by `model` alone works across apps
        for harness-vs-harness comparison at a fixed model. Results refresh weekly and include the source snapshot
        window in `meta`.
        
        Licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): reuse and republish with attribution to OpenRouter."""
        return self._json(_GET_SESSION_COST, "/datasets/session-cost", params, None, include_response)

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
    def list_external_users(self, *, params: _T.ListExternalUsersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListExternalUsers200, _Errors]: ...
    @_t.overload
    def list_external_users(self, *, params: _T.ListExternalUsersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListExternalUsers200, _HttpClientResponse], _Errors]: ...
    def list_external_users(self, *, params: _T.ListExternalUsersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List registrations belonging to the authenticated organization. Inactive registrations are excluded by default. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_EXTERNAL_USERS, "/external-users", params, None, include_response)

    @_t.overload
    def create_external_user(self, *, payload: _T.CreateExternalUserRequestJson, params: _T.CreateExternalUserParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateExternalUser201, _Errors]: ...
    @_t.overload
    def create_external_user(self, *, payload: _T.CreateExternalUserRequestJson, params: _T.CreateExternalUserParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateExternalUser201, _HttpClientResponse], _Errors]: ...
    def create_external_user(self, *, payload: _T.CreateExternalUserRequestJson, params: _T.CreateExternalUserParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Register a caller-supplied tracking ID under the authenticated organization. No login account, policy, or credentials are created. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_EXTERNAL_USER, "/external-users", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_external_user(self, user: str, *, params: _T.GetExternalUserParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetExternalUser200, _Errors]: ...
    @_t.overload
    def get_external_user(self, user: str, *, params: _T.GetExternalUserParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetExternalUser200, _HttpClientResponse], _Errors]: ...
    def get_external_user(self, user: str, *, params: _T.GetExternalUserParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieve an active or inactive registration by its URL-encoded, caller-supplied tracking ID. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_EXTERNAL_USER, _c.encoded_path("/external-users/{}", user), params, None, include_response)

    @_t.overload
    def delete_external_user(self, user: str, *, params: _T.DeleteExternalUserParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def delete_external_user(self, user: str, *, params: _T.DeleteExternalUserParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def delete_external_user(self, user: str, *, params: _T.DeleteExternalUserParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Soft-deactivate a registration while retaining its tracking ID. Repeat deactivation succeeds. This does not block inference; reactivate through PATCH. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_EXTERNAL_USER, _c.encoded_path("/external-users/{}", user), params, None, include_response)

    @_t.overload
    def update_external_user(self, user: str, *, payload: _T.UpdateExternalUserRequestJson, params: _T.UpdateExternalUserParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateExternalUser200, _Errors]: ...
    @_t.overload
    def update_external_user(self, user: str, *, payload: _T.UpdateExternalUserRequestJson, params: _T.UpdateExternalUserParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateExternalUser200, _HttpClientResponse], _Errors]: ...
    def update_external_user(self, user: str, *, payload: _T.UpdateExternalUserRequestJson, params: _T.UpdateExternalUserParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update registration state without changing identity. State changes do not enforce inference access. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_EXTERNAL_USER, _c.encoded_path("/external-users/{}", user), params, _c.json_body(payload), include_response)

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
        """Uploads a file to be referenced in future API calls. The file is stored under the workspace of the authenticating API key. Maximum file size: 100 MB; empty files are rejected. The file type is determined from the file contents — not the filename or the declared content type — and must be a PDF, a PNG/JPEG/GIF/WebP image, a DOCX/XLSX/PPTX document, an MP3/WAV/FLAC/OGG audio file, or UTF-8 text. Text is reported by its structure as `application/json`, `application/x-ndjson`, `text/csv`, `text/markdown`, or `text/plain`."""
        return self._json(_UPLOAD_FILE, "/files", params, _c.form_body(payload), include_response)

    @_t.overload
    def get_file_metadata(self, file_id: str, *, params: _T.GetFileMetadataParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetFileMetadata200, _Errors]: ...
    @_t.overload
    def get_file_metadata(self, file_id: str, *, params: _T.GetFileMetadataParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetFileMetadata200, _HttpClientResponse], _Errors]: ...
    def get_file_metadata(self, file_id: str, *, params: _T.GetFileMetadataParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves metadata for a single file owned by the requesting workspace."""
        return self._json(_GET_FILE_METADATA, _c.encoded_path("/files/{}", file_id), params, None, include_response)

    @_t.overload
    def delete_file(self, file_id: str, *, params: _T.DeleteFileParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteFile200, _Errors]: ...
    @_t.overload
    def delete_file(self, file_id: str, *, params: _T.DeleteFileParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteFile200, _HttpClientResponse], _Errors]: ...
    def delete_file(self, file_id: str, *, params: _T.DeleteFileParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a file owned by the requesting workspace. Deletion is irreversible."""
        return self._json(_DELETE_FILE, _c.encoded_path("/files/{}", file_id), params, None, include_response)

    @_t.overload
    def download_file_content(self, file_id: str, *, params: _T.DownloadFileContentParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def download_file_content(self, file_id: str, *, params: _T.DownloadFileContentParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def download_file_content(self, file_id: str, *, params: _T.DownloadFileContentParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Downloads the raw bytes of a file. Only files created server-side are downloadable; uploaded files return 400."""
        return self._json(_DOWNLOAD_FILE_CONTENT, _c.encoded_path("/files/{}/content", file_id), params, None, include_response)

    def download_file_content_stream(self, file_id: str, *, params: _T.DownloadFileContentParams | None = None) -> _Stream[bytes, _HttpClientError]:
        """Downloads the raw bytes of a file. Only files created server-side are downloadable; uploaded files return 400."""
        return self._binary(_DOWNLOAD_FILE_CONTENT_STREAM, _c.encoded_path("/files/{}/content", file_id), params, None)

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
        """Get stored prompt, completion, and error content for a generation"""
        return self._json(_LIST_GENERATION_CONTENT, "/generation/content", params, None, include_response)

    @_t.overload
    def submit_generation_feedback(self, *, payload: _T.SubmitGenerationFeedbackRequestJson, params: _T.SubmitGenerationFeedbackParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.SubmitGenerationFeedback200, _Errors]: ...
    @_t.overload
    def submit_generation_feedback(self, *, payload: _T.SubmitGenerationFeedbackRequestJson, params: _T.SubmitGenerationFeedbackParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.SubmitGenerationFeedback200, _HttpClientResponse], _Errors]: ...
    def submit_generation_feedback(self, *, payload: _T.SubmitGenerationFeedbackRequestJson, params: _T.SubmitGenerationFeedbackParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Submit structured feedback on a generation the authenticated user made. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_SUBMIT_GENERATION_FEEDBACK, "/generation/feedback", params, _c.json_body(payload), include_response)

    @_t.overload
    def list_guardrails(self, *, params: _T.ListGuardrailsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListGuardrails200, _Errors]: ...
    @_t.overload
    def list_guardrails(self, *, params: _T.ListGuardrailsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListGuardrails200, _HttpClientResponse], _Errors]: ...
    def list_guardrails(self, *, params: _T.ListGuardrailsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all guardrails for the authenticated user. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_GUARDRAILS, "/guardrails", params, None, include_response)

    @_t.overload
    def create_guardrail(self, *, payload: _T.CreateGuardrailRequestJson, params: _T.CreateGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateGuardrail201, _Errors]: ...
    @_t.overload
    def create_guardrail(self, *, payload: _T.CreateGuardrailRequestJson, params: _T.CreateGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateGuardrail201, _HttpClientResponse], _Errors]: ...
    def create_guardrail(self, *, payload: _T.CreateGuardrailRequestJson, params: _T.CreateGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new guardrail for the authenticated user. A newly created guardrail enforces nothing until it is assigned to API keys or organization members; `workspace_id` places the guardrail in a workspace but does not apply it to that workspace's traffic. To restrict all traffic in a workspace, update the workspace's default guardrail instead. Set `allowed_data_regions` to enforce [In-Region Routing](https://openrouter.ai/docs/guides/features/in-region-routing#enforcing-in-region-routing-with-guardrails): governed requests must arrive through one of the listed OpenRouter domains and are rejected with a 403 otherwise. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_GUARDRAIL, "/guardrails", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_guardrail(self, id: str, *, params: _T.GetGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetGuardrail200, _Errors]: ...
    @_t.overload
    def get_guardrail(self, id: str, *, params: _T.GetGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetGuardrail200, _HttpClientResponse], _Errors]: ...
    def get_guardrail(self, id: str, *, params: _T.GetGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a single guardrail by ID. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_GUARDRAIL, _c.encoded_path("/guardrails/{}", id), params, None, include_response)

    @_t.overload
    def delete_guardrail(self, id: str, *, params: _T.DeleteGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteGuardrail200, _Errors]: ...
    @_t.overload
    def delete_guardrail(self, id: str, *, params: _T.DeleteGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteGuardrail200, _HttpClientResponse], _Errors]: ...
    def delete_guardrail(self, id: str, *, params: _T.DeleteGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an existing guardrail. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_GUARDRAIL, _c.encoded_path("/guardrails/{}", id), params, None, include_response)

    @_t.overload
    def update_guardrail(self, id: str, *, payload: _T.UpdateGuardrailRequestJson, params: _T.UpdateGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateGuardrail200, _Errors]: ...
    @_t.overload
    def update_guardrail(self, id: str, *, payload: _T.UpdateGuardrailRequestJson, params: _T.UpdateGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateGuardrail200, _HttpClientResponse], _Errors]: ...
    def update_guardrail(self, id: str, *, payload: _T.UpdateGuardrailRequestJson, params: _T.UpdateGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update an existing guardrail, or materialize an unconfigured workspace default guardrail. Collection fields use replace semantics: send the full desired set on every update. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_GUARDRAIL, _c.encoded_path("/guardrails/{}", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_guardrail_key_assignments(self, id: str, *, params: _T.ListGuardrailKeyAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListGuardrailKeyAssignments200, _Errors]: ...
    @_t.overload
    def list_guardrail_key_assignments(self, id: str, *, params: _T.ListGuardrailKeyAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListGuardrailKeyAssignments200, _HttpClientResponse], _Errors]: ...
    def list_guardrail_key_assignments(self, id: str, *, params: _T.ListGuardrailKeyAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all API key assignments for a specific guardrail. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_GUARDRAIL_KEY_ASSIGNMENTS, _c.encoded_path("/guardrails/{}/assignments/keys", id), params, None, include_response)

    @_t.overload
    def bulk_assign_keys_to_guardrail(self, id: str, *, payload: _T.BulkAssignKeysToGuardrailRequestJson, params: _T.BulkAssignKeysToGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkAssignKeysToGuardrail200, _Errors]: ...
    @_t.overload
    def bulk_assign_keys_to_guardrail(self, id: str, *, payload: _T.BulkAssignKeysToGuardrailRequestJson, params: _T.BulkAssignKeysToGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkAssignKeysToGuardrail200, _HttpClientResponse], _Errors]: ...
    def bulk_assign_keys_to_guardrail(self, id: str, *, payload: _T.BulkAssignKeysToGuardrailRequestJson, params: _T.BulkAssignKeysToGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Assign multiple API keys to a specific guardrail. A key may hold at most one guardrail; assigning replaces any existing assignment. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_ASSIGN_KEYS_TO_GUARDRAIL, _c.encoded_path("/guardrails/{}/assignments/keys", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def bulk_unassign_keys_from_guardrail(self, id: str, *, payload: _T.BulkUnassignKeysFromGuardrailRequestJson, params: _T.BulkUnassignKeysFromGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkUnassignKeysFromGuardrail200, _Errors]: ...
    @_t.overload
    def bulk_unassign_keys_from_guardrail(self, id: str, *, payload: _T.BulkUnassignKeysFromGuardrailRequestJson, params: _T.BulkUnassignKeysFromGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkUnassignKeysFromGuardrail200, _HttpClientResponse], _Errors]: ...
    def bulk_unassign_keys_from_guardrail(self, id: str, *, payload: _T.BulkUnassignKeysFromGuardrailRequestJson, params: _T.BulkUnassignKeysFromGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Unassign multiple API keys from a specific guardrail. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_UNASSIGN_KEYS_FROM_GUARDRAIL, _c.encoded_path("/guardrails/{}/assignments/keys/remove", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_guardrail_member_assignments(self, id: str, *, params: _T.ListGuardrailMemberAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListGuardrailMemberAssignments200, _Errors]: ...
    @_t.overload
    def list_guardrail_member_assignments(self, id: str, *, params: _T.ListGuardrailMemberAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListGuardrailMemberAssignments200, _HttpClientResponse], _Errors]: ...
    def list_guardrail_member_assignments(self, id: str, *, params: _T.ListGuardrailMemberAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all organization member assignments for a specific guardrail. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_GUARDRAIL_MEMBER_ASSIGNMENTS, _c.encoded_path("/guardrails/{}/assignments/members", id), params, None, include_response)

    @_t.overload
    def bulk_assign_members_to_guardrail(self, id: str, *, payload: _T.BulkAssignMembersToGuardrailRequestJson, params: _T.BulkAssignMembersToGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkAssignMembersToGuardrail200, _Errors]: ...
    @_t.overload
    def bulk_assign_members_to_guardrail(self, id: str, *, payload: _T.BulkAssignMembersToGuardrailRequestJson, params: _T.BulkAssignMembersToGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkAssignMembersToGuardrail200, _HttpClientResponse], _Errors]: ...
    def bulk_assign_members_to_guardrail(self, id: str, *, payload: _T.BulkAssignMembersToGuardrailRequestJson, params: _T.BulkAssignMembersToGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Assign multiple organization members to a specific guardrail. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_ASSIGN_MEMBERS_TO_GUARDRAIL, _c.encoded_path("/guardrails/{}/assignments/members", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def bulk_unassign_members_from_guardrail(self, id: str, *, payload: _T.BulkUnassignMembersFromGuardrailRequestJson, params: _T.BulkUnassignMembersFromGuardrailParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkUnassignMembersFromGuardrail200, _Errors]: ...
    @_t.overload
    def bulk_unassign_members_from_guardrail(self, id: str, *, payload: _T.BulkUnassignMembersFromGuardrailRequestJson, params: _T.BulkUnassignMembersFromGuardrailParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkUnassignMembersFromGuardrail200, _HttpClientResponse], _Errors]: ...
    def bulk_unassign_members_from_guardrail(self, id: str, *, payload: _T.BulkUnassignMembersFromGuardrailRequestJson, params: _T.BulkUnassignMembersFromGuardrailParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Unassign multiple organization members from a specific guardrail. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_UNASSIGN_MEMBERS_FROM_GUARDRAIL, _c.encoded_path("/guardrails/{}/assignments/members/remove", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_key_assignments(self, *, params: _T.ListKeyAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListKeyAssignments200, _Errors]: ...
    @_t.overload
    def list_key_assignments(self, *, params: _T.ListKeyAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListKeyAssignments200, _HttpClientResponse], _Errors]: ...
    def list_key_assignments(self, *, params: _T.ListKeyAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all API key guardrail assignments for the authenticated user. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_KEY_ASSIGNMENTS, "/guardrails/assignments/keys", params, None, include_response)

    @_t.overload
    def list_member_assignments(self, *, params: _T.ListMemberAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListMemberAssignments200, _Errors]: ...
    @_t.overload
    def list_member_assignments(self, *, params: _T.ListMemberAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListMemberAssignments200, _HttpClientResponse], _Errors]: ...
    def list_member_assignments(self, *, params: _T.ListMemberAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all organization member guardrail assignments for the authenticated user. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_MEMBER_ASSIGNMENTS, "/guardrails/assignments/members", params, None, include_response)

    @_t.overload
    def list_account_policies(self, *, params: _T.ListAccountPoliciesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAccountPolicies200, _Errors]: ...
    @_t.overload
    def list_account_policies(self, *, params: _T.ListAccountPoliciesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAccountPolicies200, _HttpClientResponse], _Errors]: ...
    def list_account_policies(self, *, params: _T.ListAccountPoliciesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the workspace-wide policies that apply across workspaces in the account. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_ACCOUNT_POLICIES, "/guardrails/policies/account", params, None, include_response)

    @_t.overload
    def create_account_policy(self, *, payload: _T.CreateAccountPolicyRequestJson, params: _T.CreateAccountPolicyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateAccountPolicy201, _Errors]: ...
    @_t.overload
    def create_account_policy(self, *, payload: _T.CreateAccountPolicyRequestJson, params: _T.CreateAccountPolicyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateAccountPolicy201, _HttpClientResponse], _Errors]: ...
    def create_account_policy(self, *, payload: _T.CreateAccountPolicyRequestJson, params: _T.CreateAccountPolicyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a workspace-wide budget, moderation, or model availability policy. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_ACCOUNT_POLICY, "/guardrails/policies/account", params, _c.json_body(payload), include_response)

    @_t.overload
    def update_account_policy(self, id: str, *, payload: _T.UpdateAccountPolicyRequestJson, params: _T.UpdateAccountPolicyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateAccountPolicy200, _Errors]: ...
    @_t.overload
    def update_account_policy(self, id: str, *, payload: _T.UpdateAccountPolicyRequestJson, params: _T.UpdateAccountPolicyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateAccountPolicy200, _HttpClientResponse], _Errors]: ...
    def update_account_policy(self, id: str, *, payload: _T.UpdateAccountPolicyRequestJson, params: _T.UpdateAccountPolicyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Replace a workspace-wide policy and its workspace coverage. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_ACCOUNT_POLICY, _c.encoded_path("/guardrails/policies/account/{}", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def delete_account_policy(self, id: str, *, params: _T.DeleteAccountPolicyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteAccountPolicy200, _Errors]: ...
    @_t.overload
    def delete_account_policy(self, id: str, *, params: _T.DeleteAccountPolicyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteAccountPolicy200, _HttpClientResponse], _Errors]: ...
    def delete_account_policy(self, id: str, *, params: _T.DeleteAccountPolicyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a workspace-wide policy. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_ACCOUNT_POLICY, _c.encoded_path("/guardrails/policies/account/{}", id), params, None, include_response)

    @_t.overload
    def get_api_key_policy_assignment(self, hash: str, *, params: _T.GetApiKeyPolicyAssignmentParams, include_response: _t.Literal[False] = False) -> _Effect[_T.GetApiKeyPolicyAssignment200, _Errors]: ...
    @_t.overload
    def get_api_key_policy_assignment(self, hash: str, *, params: _T.GetApiKeyPolicyAssignmentParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetApiKeyPolicyAssignment200, _HttpClientResponse], _Errors]: ...
    def get_api_key_policy_assignment(self, hash: str, *, params: _T.GetApiKeyPolicyAssignmentParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get the policies of one type that apply to an API key in a workspace. Requires a management key with write access. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_API_KEY_POLICY_ASSIGNMENT, _c.encoded_path("/guardrails/policies/assignments/api-keys/{}", hash), params, None, include_response)

    @_t.overload
    def change_api_key_policy_assignment(self, hash: str, *, payload: _T.ChangeApiKeyPolicyAssignmentRequestJson, params: _T.ChangeApiKeyPolicyAssignmentParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ChangeApiKeyPolicyAssignment200, _Errors]: ...
    @_t.overload
    def change_api_key_policy_assignment(self, hash: str, *, payload: _T.ChangeApiKeyPolicyAssignmentRequestJson, params: _T.ChangeApiKeyPolicyAssignmentParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ChangeApiKeyPolicyAssignment200, _HttpClientResponse], _Errors]: ...
    def change_api_key_policy_assignment(self, hash: str, *, payload: _T.ChangeApiKeyPolicyAssignmentRequestJson, params: _T.ChangeApiKeyPolicyAssignmentParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Assign or unassign one policy for an API key. Fails with 409 when `expected_assignment` no longer matches the stored state. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CHANGE_API_KEY_POLICY_ASSIGNMENT, _c.encoded_path("/guardrails/policies/assignments/api-keys/{}", hash), params, _c.json_body(payload), include_response)

    @_t.overload
    def get_member_policy_assignment(self, member_id: str, *, params: _T.GetMemberPolicyAssignmentParams, include_response: _t.Literal[False] = False) -> _Effect[_T.GetMemberPolicyAssignment200, _Errors]: ...
    @_t.overload
    def get_member_policy_assignment(self, member_id: str, *, params: _T.GetMemberPolicyAssignmentParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetMemberPolicyAssignment200, _HttpClientResponse], _Errors]: ...
    def get_member_policy_assignment(self, member_id: str, *, params: _T.GetMemberPolicyAssignmentParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get the policies of one type that apply to a member in a workspace. Requires a management key with write access. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_MEMBER_POLICY_ASSIGNMENT, _c.encoded_path("/guardrails/policies/assignments/members/{}", member_id), params, None, include_response)

    @_t.overload
    def change_member_policy_assignment(self, member_id: str, *, payload: _T.ChangeMemberPolicyAssignmentRequestJson, params: _T.ChangeMemberPolicyAssignmentParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ChangeMemberPolicyAssignment200, _Errors]: ...
    @_t.overload
    def change_member_policy_assignment(self, member_id: str, *, payload: _T.ChangeMemberPolicyAssignmentRequestJson, params: _T.ChangeMemberPolicyAssignmentParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ChangeMemberPolicyAssignment200, _HttpClientResponse], _Errors]: ...
    def change_member_policy_assignment(self, member_id: str, *, payload: _T.ChangeMemberPolicyAssignmentRequestJson, params: _T.ChangeMemberPolicyAssignmentParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Assign or unassign one policy for a member. Fails with 409 when `expected_assignment` no longer matches the stored state. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CHANGE_MEMBER_POLICY_ASSIGNMENT, _c.encoded_path("/guardrails/policies/assignments/members/{}", member_id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_budget_policies(self, *, params: _T.ListBudgetPoliciesParams, include_response: _t.Literal[False] = False) -> _Effect[_T.ListBudgetPolicies200, _Errors]: ...
    @_t.overload
    def list_budget_policies(self, *, params: _T.ListBudgetPoliciesParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListBudgetPolicies200, _HttpClientResponse], _Errors]: ...
    def list_budget_policies(self, *, params: _T.ListBudgetPoliciesParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the budget policies in a workspace. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_BUDGET_POLICIES, "/guardrails/policies/budget", params, None, include_response)

    @_t.overload
    def create_budget_policy(self, *, payload: _T.CreateBudgetPolicyRequestJson, params: _T.CreateBudgetPolicyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateBudgetPolicy201, _Errors]: ...
    @_t.overload
    def create_budget_policy(self, *, payload: _T.CreateBudgetPolicyRequestJson, params: _T.CreateBudgetPolicyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateBudgetPolicy201, _HttpClientResponse], _Errors]: ...
    def create_budget_policy(self, *, payload: _T.CreateBudgetPolicyRequestJson, params: _T.CreateBudgetPolicyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a budget policy in a workspace. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_BUDGET_POLICY, "/guardrails/policies/budget", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_budget_policy(self, id: str, *, params: _T.GetBudgetPolicyParams, include_response: _t.Literal[False] = False) -> _Effect[_T.GetBudgetPolicy200, _Errors]: ...
    @_t.overload
    def get_budget_policy(self, id: str, *, params: _T.GetBudgetPolicyParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetBudgetPolicy200, _HttpClientResponse], _Errors]: ...
    def get_budget_policy(self, id: str, *, params: _T.GetBudgetPolicyParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a budget policy with its member and API key assignments. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_BUDGET_POLICY, _c.encoded_path("/guardrails/policies/budget/{}", id), params, None, include_response)

    @_t.overload
    def update_budget_policy(self, id: str, *, payload: _T.UpdateBudgetPolicyRequestJson, params: _T.UpdateBudgetPolicyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateBudgetPolicy200, _Errors]: ...
    @_t.overload
    def update_budget_policy(self, id: str, *, payload: _T.UpdateBudgetPolicyRequestJson, params: _T.UpdateBudgetPolicyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateBudgetPolicy200, _HttpClientResponse], _Errors]: ...
    def update_budget_policy(self, id: str, *, payload: _T.UpdateBudgetPolicyRequestJson, params: _T.UpdateBudgetPolicyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Replace a budget policy's name and config, and optionally its assignments. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_BUDGET_POLICY, _c.encoded_path("/guardrails/policies/budget/{}", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def delete_budget_policy(self, id: str, *, params: _T.DeleteBudgetPolicyParams, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteBudgetPolicy200, _Errors]: ...
    @_t.overload
    def delete_budget_policy(self, id: str, *, params: _T.DeleteBudgetPolicyParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteBudgetPolicy200, _HttpClientResponse], _Errors]: ...
    def delete_budget_policy(self, id: str, *, params: _T.DeleteBudgetPolicyParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a budget policy. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_BUDGET_POLICY, _c.encoded_path("/guardrails/policies/budget/{}", id), params, None, include_response)

    @_t.overload
    def list_model_availability_policies(self, *, params: _T.ListModelAvailabilityPoliciesParams, include_response: _t.Literal[False] = False) -> _Effect[_T.ListModelAvailabilityPolicies200, _Errors]: ...
    @_t.overload
    def list_model_availability_policies(self, *, params: _T.ListModelAvailabilityPoliciesParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListModelAvailabilityPolicies200, _HttpClientResponse], _Errors]: ...
    def list_model_availability_policies(self, *, params: _T.ListModelAvailabilityPoliciesParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the model availability policies in a workspace. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_MODEL_AVAILABILITY_POLICIES, "/guardrails/policies/model-availability", params, None, include_response)

    @_t.overload
    def create_model_availability_policy(self, *, payload: _T.CreateModelAvailabilityPolicyRequestJson, params: _T.CreateModelAvailabilityPolicyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateModelAvailabilityPolicy201, _Errors]: ...
    @_t.overload
    def create_model_availability_policy(self, *, payload: _T.CreateModelAvailabilityPolicyRequestJson, params: _T.CreateModelAvailabilityPolicyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateModelAvailabilityPolicy201, _HttpClientResponse], _Errors]: ...
    def create_model_availability_policy(self, *, payload: _T.CreateModelAvailabilityPolicyRequestJson, params: _T.CreateModelAvailabilityPolicyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a model availability policy in a workspace. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_MODEL_AVAILABILITY_POLICY, "/guardrails/policies/model-availability", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_model_availability_policy(self, id: str, *, params: _T.GetModelAvailabilityPolicyParams, include_response: _t.Literal[False] = False) -> _Effect[_T.GetModelAvailabilityPolicy200, _Errors]: ...
    @_t.overload
    def get_model_availability_policy(self, id: str, *, params: _T.GetModelAvailabilityPolicyParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetModelAvailabilityPolicy200, _HttpClientResponse], _Errors]: ...
    def get_model_availability_policy(self, id: str, *, params: _T.GetModelAvailabilityPolicyParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a model availability policy with its member and API key assignments. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_MODEL_AVAILABILITY_POLICY, _c.encoded_path("/guardrails/policies/model-availability/{}", id), params, None, include_response)

    @_t.overload
    def update_model_availability_policy(self, id: str, *, payload: _T.UpdateModelAvailabilityPolicyRequestJson, params: _T.UpdateModelAvailabilityPolicyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateModelAvailabilityPolicy200, _Errors]: ...
    @_t.overload
    def update_model_availability_policy(self, id: str, *, payload: _T.UpdateModelAvailabilityPolicyRequestJson, params: _T.UpdateModelAvailabilityPolicyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateModelAvailabilityPolicy200, _HttpClientResponse], _Errors]: ...
    def update_model_availability_policy(self, id: str, *, payload: _T.UpdateModelAvailabilityPolicyRequestJson, params: _T.UpdateModelAvailabilityPolicyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Replace a model availability policy's name and config, and optionally its assignments. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_MODEL_AVAILABILITY_POLICY, _c.encoded_path("/guardrails/policies/model-availability/{}", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def delete_model_availability_policy(self, id: str, *, params: _T.DeleteModelAvailabilityPolicyParams, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteModelAvailabilityPolicy200, _Errors]: ...
    @_t.overload
    def delete_model_availability_policy(self, id: str, *, params: _T.DeleteModelAvailabilityPolicyParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteModelAvailabilityPolicy200, _HttpClientResponse], _Errors]: ...
    def delete_model_availability_policy(self, id: str, *, params: _T.DeleteModelAvailabilityPolicyParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a model availability policy. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_MODEL_AVAILABILITY_POLICY, _c.encoded_path("/guardrails/policies/model-availability/{}", id), params, None, include_response)

    @_t.overload
    def list_moderation_policies(self, *, params: _T.ListModerationPoliciesParams, include_response: _t.Literal[False] = False) -> _Effect[_T.ListModerationPolicies200, _Errors]: ...
    @_t.overload
    def list_moderation_policies(self, *, params: _T.ListModerationPoliciesParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListModerationPolicies200, _HttpClientResponse], _Errors]: ...
    def list_moderation_policies(self, *, params: _T.ListModerationPoliciesParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the moderation policies in a workspace. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_MODERATION_POLICIES, "/guardrails/policies/moderation", params, None, include_response)

    @_t.overload
    def create_moderation_policy(self, *, payload: _T.CreateModerationPolicyRequestJson, params: _T.CreateModerationPolicyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateModerationPolicy201, _Errors]: ...
    @_t.overload
    def create_moderation_policy(self, *, payload: _T.CreateModerationPolicyRequestJson, params: _T.CreateModerationPolicyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateModerationPolicy201, _HttpClientResponse], _Errors]: ...
    def create_moderation_policy(self, *, payload: _T.CreateModerationPolicyRequestJson, params: _T.CreateModerationPolicyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a moderation policy in a workspace. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_MODERATION_POLICY, "/guardrails/policies/moderation", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_moderation_policy(self, id: str, *, params: _T.GetModerationPolicyParams, include_response: _t.Literal[False] = False) -> _Effect[_T.GetModerationPolicy200, _Errors]: ...
    @_t.overload
    def get_moderation_policy(self, id: str, *, params: _T.GetModerationPolicyParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetModerationPolicy200, _HttpClientResponse], _Errors]: ...
    def get_moderation_policy(self, id: str, *, params: _T.GetModerationPolicyParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a moderation policy with its member and API key assignments. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_MODERATION_POLICY, _c.encoded_path("/guardrails/policies/moderation/{}", id), params, None, include_response)

    @_t.overload
    def update_moderation_policy(self, id: str, *, payload: _T.UpdateModerationPolicyRequestJson, params: _T.UpdateModerationPolicyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateModerationPolicy200, _Errors]: ...
    @_t.overload
    def update_moderation_policy(self, id: str, *, payload: _T.UpdateModerationPolicyRequestJson, params: _T.UpdateModerationPolicyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateModerationPolicy200, _HttpClientResponse], _Errors]: ...
    def update_moderation_policy(self, id: str, *, payload: _T.UpdateModerationPolicyRequestJson, params: _T.UpdateModerationPolicyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Replace a moderation policy's name and config, and optionally its assignments. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_MODERATION_POLICY, _c.encoded_path("/guardrails/policies/moderation/{}", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def delete_moderation_policy(self, id: str, *, params: _T.DeleteModerationPolicyParams, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteModerationPolicy200, _Errors]: ...
    @_t.overload
    def delete_moderation_policy(self, id: str, *, params: _T.DeleteModerationPolicyParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteModerationPolicy200, _HttpClientResponse], _Errors]: ...
    def delete_moderation_policy(self, id: str, *, params: _T.DeleteModerationPolicyParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a moderation policy. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_MODERATION_POLICY, _c.encoded_path("/guardrails/policies/moderation/{}", id), params, None, include_response)

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
        return self._json(_LIST_IMAGE_MODEL_ENDPOINTS, _c.encoded_path("/images/models/{}/{}/endpoints", author, slug), params, None, include_response)

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
        """List all API keys for the authenticated user. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST, "/keys", params, None, include_response)

    @_t.overload
    def create_keys(self, *, payload: _T.CreateKeysRequestJson, params: _T.CreateKeysParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateKeys201, _Errors]: ...
    @_t.overload
    def create_keys(self, *, payload: _T.CreateKeysRequestJson, params: _T.CreateKeysParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateKeys201, _HttpClientResponse], _Errors]: ...
    def create_keys(self, *, payload: _T.CreateKeysRequestJson, params: _T.CreateKeysParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new API key for the authenticated user. The plaintext `key` is returned only in this response. Treat it as a write-only, sensitive value; it cannot be retrieved later. Authenticate with a [management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys). The optional `external` object associates the key with a partner-defined user and lookup key."""
        return self._json(_CREATE_KEYS, "/keys", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_key(self, hash: str, *, params: _T.GetKeyParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetKey200, _Errors]: ...
    @_t.overload
    def get_key(self, hash: str, *, params: _T.GetKeyParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetKey200, _HttpClientResponse], _Errors]: ...
    def get_key(self, hash: str, *, params: _T.GetKeyParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a single API key by hash. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_KEY, _c.encoded_path("/keys/{}", hash), params, None, include_response)

    @_t.overload
    def delete_keys(self, hash: str, *, params: _T.DeleteKeysParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteKeys200, _Errors]: ...
    @_t.overload
    def delete_keys(self, hash: str, *, params: _T.DeleteKeysParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteKeys200, _HttpClientResponse], _Errors]: ...
    def delete_keys(self, hash: str, *, params: _T.DeleteKeysParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an existing API key. Authenticate with a [management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys)."""
        return self._json(_DELETE_KEYS, _c.encoded_path("/keys/{}", hash), params, None, include_response)

    @_t.overload
    def update_keys(self, hash: str, *, payload: _T.UpdateKeysRequestJson, params: _T.UpdateKeysParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateKeys200, _Errors]: ...
    @_t.overload
    def update_keys(self, hash: str, *, payload: _T.UpdateKeysRequestJson, params: _T.UpdateKeysParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateKeys200, _HttpClientResponse], _Errors]: ...
    def update_keys(self, hash: str, *, payload: _T.UpdateKeysRequestJson, params: _T.UpdateKeysParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update an existing API key. Authenticate with a [management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys).
        
        Set `workspace_id` to move the key to another workspace.
        
        <Warning>
        The request body accepts only the fields listed below, and unrecognized fields are ignored. If the body contains none of the accepted fields, the request fails with `400` and the message `No update fields provided`.
        </Warning>"""
        return self._json(_UPDATE_KEYS, _c.encoded_path("/keys/{}", hash), params, _c.json_body(payload), include_response)

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
        return self._json(_GET_MODEL, _c.encoded_path("/model/{}/{}", author, slug), params, None, include_response)

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
        return self._json(_LIST_ENDPOINTS, _c.encoded_path("/models/{}/{}/endpoints", author, slug), params, None, include_response)

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
        """List models filtered by user provider preferences, [privacy settings](https://openrouter.ai/docs/guides/privacy/provider-logging), and [guardrails](https://openrouter.ai/docs/guides/features/guardrails). Returns text-output models by default; pass `output_modalities` (a comma-separated list of `text`, `image`, `embeddings`, `audio`, `video`, `rerank`, `speech`, `transcription`, or `all`) to include other modalities. If requesting through a regional hostname, the results will be filtered to models that satisfy in-region routing for that region."""
        return self._json(_LIST_MODELS_USER, "/models/user", params, None, include_response)

    @_t.overload
    def list_oauth_jwks(self, *, params: _T.ListOauthJwksParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListOauthJwks200, _Errors]: ...
    @_t.overload
    def list_oauth_jwks(self, *, params: _T.ListOauthJwksParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListOauthJwks200, _HttpClientResponse], _Errors]: ...
    def list_oauth_jwks(self, *, params: _T.ListOauthJwksParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """RFC 7517 JWK Set containing the public keys OpenRouter signs access tokens with."""
        return self._json(_LIST_OAUTH_JWKS, "/oauth/jwks", params, None, include_response)

    @_t.overload
    def create_oauth_token(self, *, payload: _T.CreateOauthTokenRequestFormUrlEncoded, params: _T.CreateOauthTokenParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateOauthToken200, _Errors]: ...
    @_t.overload
    def create_oauth_token(self, *, payload: _T.CreateOauthTokenRequestFormUrlEncoded, params: _T.CreateOauthTokenParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateOauthToken200, _HttpClientResponse], _Errors]: ...
    def create_oauth_token(self, *, payload: _T.CreateOauthTokenRequestFormUrlEncoded, params: _T.CreateOauthTokenParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """RFC 8693 token exchange. Presents a JWT from an issuer your organization trusts (Settings → Workload identity) and receives a short-lived OpenRouter access token that acts as the API key the matching federation policy targets."""
        return self._json(_CREATE_OAUTH_TOKEN, "/oauth/token", params, _c.url_params_body(payload), include_response)

    @_t.overload
    def list_observability_destinations(self, *, params: _T.ListObservabilityDestinationsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListObservabilityDestinations200, _Errors]: ...
    @_t.overload
    def list_observability_destinations(self, *, params: _T.ListObservabilityDestinationsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListObservabilityDestinations200, _HttpClientResponse], _Errors]: ...
    def list_observability_destinations(self, *, params: _T.ListObservabilityDestinationsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the observability destinations configured for the authenticated entity's default workspace. Use the `workspace_id` query parameter to scope the result to a different workspace. Only destinations with stable release status are surfaced — destinations of other types are excluded. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_OBSERVABILITY_DESTINATIONS, "/observability/destinations", params, None, include_response)

    @_t.overload
    def create_observability_destination(self, *, payload: _T.CreateObservabilityDestinationRequestJson, params: _T.CreateObservabilityDestinationParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateObservabilityDestination201, _Errors]: ...
    @_t.overload
    def create_observability_destination(self, *, payload: _T.CreateObservabilityDestinationRequestJson, params: _T.CreateObservabilityDestinationParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateObservabilityDestination201, _HttpClientResponse], _Errors]: ...
    def create_observability_destination(self, *, payload: _T.CreateObservabilityDestinationRequestJson, params: _T.CreateObservabilityDestinationParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new observability destination. A maximum of 5 destinations per type is allowed. Defaults to the authenticated entity's default workspace; use the `workspace_id` body field to scope to a different workspace. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_OBSERVABILITY_DESTINATION, "/observability/destinations", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_observability_destination(self, id: str, *, params: _T.GetObservabilityDestinationParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetObservabilityDestination200, _Errors]: ...
    @_t.overload
    def get_observability_destination(self, id: str, *, params: _T.GetObservabilityDestinationParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetObservabilityDestination200, _HttpClientResponse], _Errors]: ...
    def get_observability_destination(self, id: str, *, params: _T.GetObservabilityDestinationParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Fetch a single observability destination by its UUID. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_OBSERVABILITY_DESTINATION, _c.encoded_path("/observability/destinations/{}", id), params, None, include_response)

    @_t.overload
    def delete_observability_destination(self, id: str, *, params: _T.DeleteObservabilityDestinationParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteObservabilityDestination200, _Errors]: ...
    @_t.overload
    def delete_observability_destination(self, id: str, *, params: _T.DeleteObservabilityDestinationParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteObservabilityDestination200, _HttpClientResponse], _Errors]: ...
    def delete_observability_destination(self, id: str, *, params: _T.DeleteObservabilityDestinationParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an existing observability destination. This performs a soft delete. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_OBSERVABILITY_DESTINATION, _c.encoded_path("/observability/destinations/{}", id), params, None, include_response)

    @_t.overload
    def update_observability_destination(self, id: str, *, payload: _T.UpdateObservabilityDestinationRequestJson, params: _T.UpdateObservabilityDestinationParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateObservabilityDestination200, _Errors]: ...
    @_t.overload
    def update_observability_destination(self, id: str, *, payload: _T.UpdateObservabilityDestinationRequestJson, params: _T.UpdateObservabilityDestinationParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateObservabilityDestination200, _HttpClientResponse], _Errors]: ...
    def update_observability_destination(self, id: str, *, payload: _T.UpdateObservabilityDestinationRequestJson, params: _T.UpdateObservabilityDestinationParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update an existing observability destination. Only the fields provided in the request body are updated. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_OBSERVABILITY_DESTINATION, _c.encoded_path("/observability/destinations/{}", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_organization_members(self, *, params: _T.ListOrganizationMembersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListOrganizationMembers200, _Errors]: ...
    @_t.overload
    def list_organization_members(self, *, params: _T.ListOrganizationMembersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListOrganizationMembers200, _HttpClientResponse], _Errors]: ...
    def list_organization_members(self, *, params: _T.ListOrganizationMembersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all members of the organization associated with the authenticated management key. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_ORGANIZATION_MEMBERS, "/organization/members", params, None, include_response)

    @_t.overload
    def get_organization_settings(self, *, params: _T.GetOrganizationSettingsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetOrganizationSettings200, _Errors]: ...
    @_t.overload
    def get_organization_settings(self, *, params: _T.GetOrganizationSettingsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetOrganizationSettings200, _HttpClientResponse], _Errors]: ...
    def get_organization_settings(self, *, params: _T.GetOrganizationSettingsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get the settings of the organization associated with the authenticated management key. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_ORGANIZATION_SETTINGS, "/organization/settings", params, None, include_response)

    @_t.overload
    def update_organization_settings(self, *, payload: _T.UpdateOrganizationSettingsRequestJson, params: _T.UpdateOrganizationSettingsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateOrganizationSettings200, _Errors]: ...
    @_t.overload
    def update_organization_settings(self, *, payload: _T.UpdateOrganizationSettingsRequestJson, params: _T.UpdateOrganizationSettingsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateOrganizationSettings200, _HttpClientResponse], _Errors]: ...
    def update_organization_settings(self, *, payload: _T.UpdateOrganizationSettingsRequestJson, params: _T.UpdateOrganizationSettingsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update the settings of the organization associated with the authenticated management key. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_ORGANIZATION_SETTINGS, "/organization/settings", params, _c.json_body(payload), include_response)

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
        return self._json(_GET_PRESET, _c.encoded_path("/presets/{}", slug), params, None, include_response)

    @_t.overload
    def delete_preset(self, slug: str, *, params: _T.DeletePresetParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeletePreset200, _Errors]: ...
    @_t.overload
    def delete_preset(self, slug: str, *, params: _T.DeletePresetParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeletePreset200, _HttpClientResponse], _Errors]: ...
    def delete_preset(self, slug: str, *, params: _T.DeletePresetParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Archives a preset: it no longer resolves for inference and is hidden from get and list. The preset and its versions are kept, so the slug stays taken; restore it with `POST /presets/{slug}/restore`. Deleting an already-archived preset succeeds again. A disabled preset returns 409. Requires a read-write [management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys); inference API keys are rejected. `workspace_id` may be sent as a query parameter or a JSON body field."""
        return self._json(_DELETE_PRESET, _c.encoded_path("/presets/{}", slug), params, None, include_response)

    @_t.overload
    def create_presets_chat_completions(self, slug: str, *, payload: _T.CreatePresetsChatCompletionsRequestJson, params: _T.CreatePresetsChatCompletionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreatePresetsChatCompletions200, _Errors]: ...
    @_t.overload
    def create_presets_chat_completions(self, slug: str, *, payload: _T.CreatePresetsChatCompletionsRequestJson, params: _T.CreatePresetsChatCompletionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreatePresetsChatCompletions200, _HttpClientResponse], _Errors]: ...
    def create_presets_chat_completions(self, slug: str, *, payload: _T.CreatePresetsChatCompletionsRequestJson, params: _T.CreatePresetsChatCompletionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a preset (or a new version of an existing one) from an inference request body. Only fields that overlap with the preset config are persisted; other fields (e.g. `messages`, `stream`, `prompt`) are silently ignored. Requires a read-write [management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys); inference API keys are rejected."""
        return self._json(_CREATE_PRESETS_CHAT_COMPLETIONS, _c.encoded_path("/presets/{}/chat/completions", slug), params, _c.json_body(payload), include_response)

    @_t.overload
    def create_presets_messages(self, slug: str, *, payload: _T.CreatePresetsMessagesRequestJson, params: _T.CreatePresetsMessagesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreatePresetsMessages200, _Errors]: ...
    @_t.overload
    def create_presets_messages(self, slug: str, *, payload: _T.CreatePresetsMessagesRequestJson, params: _T.CreatePresetsMessagesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreatePresetsMessages200, _HttpClientResponse], _Errors]: ...
    def create_presets_messages(self, slug: str, *, payload: _T.CreatePresetsMessagesRequestJson, params: _T.CreatePresetsMessagesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a preset (or a new version of an existing one) from an inference request body. Only fields that overlap with the preset config are persisted; other fields (e.g. `messages`, `stream`, `prompt`) are silently ignored. Requires a read-write [management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys); inference API keys are rejected."""
        return self._json(_CREATE_PRESETS_MESSAGES, _c.encoded_path("/presets/{}/messages", slug), params, _c.json_body(payload), include_response)

    @_t.overload
    def create_presets_responses(self, slug: str, *, payload: _T.CreatePresetsResponsesRequestJson, params: _T.CreatePresetsResponsesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreatePresetsResponses200, _Errors]: ...
    @_t.overload
    def create_presets_responses(self, slug: str, *, payload: _T.CreatePresetsResponsesRequestJson, params: _T.CreatePresetsResponsesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreatePresetsResponses200, _HttpClientResponse], _Errors]: ...
    def create_presets_responses(self, slug: str, *, payload: _T.CreatePresetsResponsesRequestJson, params: _T.CreatePresetsResponsesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a preset (or a new version of an existing one) from an inference request body. Only fields that overlap with the preset config are persisted; other fields (e.g. `messages`, `stream`, `prompt`) are silently ignored. Requires a read-write [management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys); inference API keys are rejected."""
        return self._json(_CREATE_PRESETS_RESPONSES, _c.encoded_path("/presets/{}/responses", slug), params, _c.json_body(payload), include_response)

    @_t.overload
    def restore_preset(self, slug: str, *, params: _T.RestorePresetParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.RestorePreset200, _Errors]: ...
    @_t.overload
    def restore_preset(self, slug: str, *, params: _T.RestorePresetParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RestorePreset200, _HttpClientResponse], _Errors]: ...
    def restore_preset(self, slug: str, *, params: _T.RestorePresetParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Re-activates an archived preset so it resolves for inference again. No version is created and the designated version is unchanged. Restoring an active preset returns it unchanged. A disabled preset returns 409. Requires a read-write [management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys); inference API keys are rejected. `workspace_id` may be sent as a query parameter or a JSON body field."""
        return self._json(_RESTORE_PRESET, _c.encoded_path("/presets/{}/restore", slug), params, None, include_response)

    @_t.overload
    def list_preset_versions(self, slug: str, *, params: _T.ListPresetVersionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListPresetVersions200, _Errors]: ...
    @_t.overload
    def list_preset_versions(self, slug: str, *, params: _T.ListPresetVersionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListPresetVersions200, _HttpClientResponse], _Errors]: ...
    def list_preset_versions(self, slug: str, *, params: _T.ListPresetVersionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists all versions of a preset, ordered by version number ascending (oldest first)."""
        return self._json(_LIST_PRESET_VERSIONS, _c.encoded_path("/presets/{}/versions", slug), params, None, include_response)

    @_t.overload
    def get_preset_version(self, slug: str, version: str, *, params: _T.GetPresetVersionParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetPresetVersion200, _Errors]: ...
    @_t.overload
    def get_preset_version(self, slug: str, version: str, *, params: _T.GetPresetVersionParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetPresetVersion200, _HttpClientResponse], _Errors]: ...
    def get_preset_version(self, slug: str, version: str, *, params: _T.GetPresetVersionParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a specific version of a preset by its slug and version number."""
        return self._json(_GET_PRESET_VERSION, _c.encoded_path("/presets/{}/versions/{}", slug, version), params, None, include_response)

    @_t.overload
    def list_private_endpoints(self, *, params: _T.ListPrivateEndpointsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListPrivateEndpoints200, _Errors]: ...
    @_t.overload
    def list_private_endpoints(self, *, params: _T.ListPrivateEndpointsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListPrivateEndpoints200, _HttpClientResponse], _Errors]: ...
    def list_private_endpoints(self, *, params: _T.ListPrivateEndpointsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the organization's private endpoints, including drafts. Requires the private endpoints entitlement. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_PRIVATE_ENDPOINTS, "/private-endpoints", params, None, include_response)

    @_t.overload
    def create_private_endpoint(self, *, payload: _T.CreatePrivateEndpointRequestJson, params: _T.CreatePrivateEndpointParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreatePrivateEndpoint201, _Errors]: ...
    @_t.overload
    def create_private_endpoint(self, *, payload: _T.CreatePrivateEndpointRequestJson, params: _T.CreatePrivateEndpointParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreatePrivateEndpoint201, _HttpClientResponse], _Errors]: ...
    def create_private_endpoint(self, *, payload: _T.CreatePrivateEndpointRequestJson, params: _T.CreatePrivateEndpointParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a private endpoint as a draft. Drafts are not routable: validate one with `POST /private-endpoints/{id}/validate`, then activate it with `POST /private-endpoints/{id}/activate`. Pass `activate` to do all three in one call; if validation fails the draft is kept and returned with the failed checks. Send an `Idempotency-Key` header to make retries safe: a repeated key with the same request returns the endpoint the first request created; reusing it with different fields returns 422 `idempotency_key_reused`. Returns 400 `parameters_invalid` when `tool_choice` is declared without `tools`. The response does not echo `declared_parameters` or `tested_parameters`; read them with `GET /private-endpoints/{id}`. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_PRIVATE_ENDPOINT, "/private-endpoints", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_private_endpoint(self, id: str, *, params: _T.GetPrivateEndpointParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetPrivateEndpoint200, _Errors]: ...
    @_t.overload
    def get_private_endpoint(self, id: str, *, params: _T.GetPrivateEndpointParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetPrivateEndpoint200, _HttpClientResponse], _Errors]: ...
    def get_private_endpoint(self, id: str, *, params: _T.GetPrivateEndpointParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get one private endpoint with its upstream configuration and current pricing. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_PRIVATE_ENDPOINT, _c.encoded_path("/private-endpoints/{}", id), params, None, include_response)

    @_t.overload
    def delete_private_endpoint(self, id: str, *, params: _T.DeletePrivateEndpointParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeletePrivateEndpoint200, _Errors]: ...
    @_t.overload
    def delete_private_endpoint(self, id: str, *, params: _T.DeletePrivateEndpointParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeletePrivateEndpoint200, _HttpClientResponse], _Errors]: ...
    def delete_private_endpoint(self, id: str, *, params: _T.DeletePrivateEndpointParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a private endpoint and stop routing to it. Pass `draft_only=true` to refuse (409) when the endpoint has been activated. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_PRIVATE_ENDPOINT, _c.encoded_path("/private-endpoints/{}", id), params, None, include_response)

    @_t.overload
    def update_private_endpoint(self, id: str, *, payload: _T.UpdatePrivateEndpointRequestJson, params: _T.UpdatePrivateEndpointParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdatePrivateEndpoint200, _Errors]: ...
    @_t.overload
    def update_private_endpoint(self, id: str, *, payload: _T.UpdatePrivateEndpointRequestJson, params: _T.UpdatePrivateEndpointParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdatePrivateEndpoint200, _HttpClientResponse], _Errors]: ...
    def update_private_endpoint(self, id: str, *, payload: _T.UpdatePrivateEndpointRequestJson, params: _T.UpdatePrivateEndpointParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Change any of the endpoint fields you own in one call; only the fields present change, and the response is the whole endpoint. `pricing` and `declared_parameters` replace their stored value, `settings` changes only the fields it names (`null` clears a limit or restores the provider default); routing picks these up for subsequent requests on drafts and active endpoints alike. `declared_zdr` and `declared_region` change on drafts and active endpoints alike; on an active endpoint the change keeps its validation and tested parameters, and routing applies it to subsequent requests. `upstream_model_id` and `base_url` re-point a draft: an omitted `upstream_model_id` or `base_url` keeps the stored one, omitted data-policy declarations are kept while the upstream is unchanged and cleared when it changes, and any change to the upstream or declarations of a draft clears earlier validation. Naming `upstream_model_id` or `base_url` on an active endpoint returns 409 `already_active` and writes nothing, even alongside other fields; delete and re-create instead. Every group is checked before anything is written: 400 `parameters_invalid` when `tool_choice` is declared without `tools` tested or declared, 400 `settings_invalid` when `max_prompt_tokens` exceeds the context length, both completion APIs are off, or `excluded_parameters` names a tested parameter, 422 `pricing_invalid` for rates the provider strategy cannot represent. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_PRIVATE_ENDPOINT, _c.encoded_path("/private-endpoints/{}", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def activate_private_endpoint(self, id: str, *, params: _T.ActivatePrivateEndpointParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ActivatePrivateEndpoint200, _Errors]: ...
    @_t.overload
    def activate_private_endpoint(self, id: str, *, params: _T.ActivatePrivateEndpointParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ActivatePrivateEndpoint200, _HttpClientResponse], _Errors]: ...
    def activate_private_endpoint(self, id: str, *, params: _T.ActivatePrivateEndpointParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Make a validated draft routable. Returns 409 when the endpoint was never validated, the validation is stale, or it is already active. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_ACTIVATE_PRIVATE_ENDPOINT, _c.encoded_path("/private-endpoints/{}/activate", id), params, None, include_response)

    @_t.overload
    def disable_private_endpoint(self, id: str, *, params: _T.DisablePrivateEndpointParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DisablePrivateEndpoint200, _Errors]: ...
    @_t.overload
    def disable_private_endpoint(self, id: str, *, params: _T.DisablePrivateEndpointParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DisablePrivateEndpoint200, _HttpClientResponse], _Errors]: ...
    def disable_private_endpoint(self, id: str, *, params: _T.DisablePrivateEndpointParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Stop routing to an active endpoint without deleting it. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DISABLE_PRIVATE_ENDPOINT, _c.encoded_path("/private-endpoints/{}/disable", id), params, None, include_response)

    @_t.overload
    def enable_private_endpoint(self, id: str, *, params: _T.EnablePrivateEndpointParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.EnablePrivateEndpoint200, _Errors]: ...
    @_t.overload
    def enable_private_endpoint(self, id: str, *, params: _T.EnablePrivateEndpointParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.EnablePrivateEndpoint200, _HttpClientResponse], _Errors]: ...
    def enable_private_endpoint(self, id: str, *, params: _T.EnablePrivateEndpointParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Resume routing to a disabled endpoint. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_ENABLE_PRIVATE_ENDPOINT, _c.encoded_path("/private-endpoints/{}/enable", id), params, None, include_response)

    @_t.overload
    def validate_private_endpoint(self, id: str, *, payload: _T.ValidatePrivateEndpointRequestJson, params: _T.ValidatePrivateEndpointParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ValidatePrivateEndpoint200, _Errors]: ...
    @_t.overload
    def validate_private_endpoint(self, id: str, *, payload: _T.ValidatePrivateEndpointRequestJson, params: _T.ValidatePrivateEndpointParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ValidatePrivateEndpoint200, _HttpClientResponse], _Errors]: ...
    def validate_private_endpoint(self, id: str, *, payload: _T.ValidatePrivateEndpointRequestJson, params: _T.ValidatePrivateEndpointParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Send a live test request to the draft endpoint using the given workspace's BYOK credential for its provider. A passing validation is required before activation. Failed checks return 200 with `passed: false`. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_VALIDATE_PRIVATE_ENDPOINT, _c.encoded_path("/private-endpoints/{}/validate", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_private_providers(self, *, params: _T.ListPrivateProvidersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListPrivateProviders200, _Errors]: ...
    @_t.overload
    def list_private_providers(self, *, params: _T.ListPrivateProvidersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListPrivateProviders200, _HttpClientResponse], _Errors]: ...
    def list_private_providers(self, *, params: _T.ListPrivateProvidersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the organization's private providers. Requires the private endpoints entitlement. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_PRIVATE_PROVIDERS, "/private-providers", params, None, include_response)

    @_t.overload
    def create_private_provider(self, *, payload: _T.CreatePrivateProviderRequestJson, params: _T.CreatePrivateProviderParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreatePrivateProvider201, _Errors]: ...
    @_t.overload
    def create_private_provider(self, *, payload: _T.CreatePrivateProviderRequestJson, params: _T.CreatePrivateProviderParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreatePrivateProvider201, _HttpClientResponse], _Errors]: ...
    def create_private_provider(self, *, payload: _T.CreatePrivateProviderRequestJson, params: _T.CreatePrivateProviderParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a private, bring-your-own-key provider visible only to your organization. Use its slug as `provider_slug` when creating private endpoints. Requires the private endpoints entitlement. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_PRIVATE_PROVIDER, "/private-providers", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_private_provider(self, slug: str, *, params: _T.GetPrivateProviderParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetPrivateProvider200, _Errors]: ...
    @_t.overload
    def get_private_provider(self, slug: str, *, params: _T.GetPrivateProviderParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetPrivateProvider200, _HttpClientResponse], _Errors]: ...
    def get_private_provider(self, slug: str, *, params: _T.GetPrivateProviderParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get one of the organization’s private providers by slug. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_PRIVATE_PROVIDER, _c.encoded_path("/private-providers/{}", slug), params, None, include_response)

    @_t.overload
    def delete_private_provider(self, slug: str, *, params: _T.DeletePrivateProviderParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeletePrivateProvider200, _Errors]: ...
    @_t.overload
    def delete_private_provider(self, slug: str, *, params: _T.DeletePrivateProviderParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeletePrivateProvider200, _HttpClientResponse], _Errors]: ...
    def delete_private_provider(self, slug: str, *, params: _T.DeletePrivateProviderParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a private provider. Refuses (409) while any private endpoint still runs under it. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_PRIVATE_PROVIDER, _c.encoded_path("/private-providers/{}", slug), params, None, include_response)

    @_t.overload
    def update_private_provider(self, slug: str, *, payload: _T.UpdatePrivateProviderRequestJson, params: _T.UpdatePrivateProviderParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdatePrivateProvider200, _Errors]: ...
    @_t.overload
    def update_private_provider(self, slug: str, *, payload: _T.UpdatePrivateProviderRequestJson, params: _T.UpdatePrivateProviderParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdatePrivateProvider200, _HttpClientResponse], _Errors]: ...
    def update_private_provider(self, slug: str, *, payload: _T.UpdatePrivateProviderRequestJson, params: _T.UpdatePrivateProviderParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update a private provider’s display name or base URL. The name and slug cannot change, and the data policy is fixed by OpenRouter, so a body with no editable field is rejected (400). [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_PRIVATE_PROVIDER, _c.encoded_path("/private-providers/{}", slug), params, _c.json_body(payload), include_response)

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
    def list_scim_group_mappings(self, *, params: _T.ListScimGroupMappingsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListScimGroupMappings200, _Errors]: ...
    @_t.overload
    def list_scim_group_mappings(self, *, params: _T.ListScimGroupMappingsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListScimGroupMappings200, _HttpClientResponse], _Errors]: ...
    def list_scim_group_mappings(self, *, params: _T.ListScimGroupMappingsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List SCIM group-to-workspace mappings for the organization. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_SCIM_GROUP_MAPPINGS, "/scim/group-mappings", params, None, include_response)

    @_t.overload
    def create_scim_group_mapping(self, *, payload: _T.CreateScimGroupMappingRequestJson, params: _T.CreateScimGroupMappingParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateScimGroupMapping201, _Errors]: ...
    @_t.overload
    def create_scim_group_mapping(self, *, payload: _T.CreateScimGroupMappingRequestJson, params: _T.CreateScimGroupMappingParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateScimGroupMapping201, _HttpClientResponse], _Errors]: ...
    def create_scim_group_mapping(self, *, payload: _T.CreateScimGroupMappingRequestJson, params: _T.CreateScimGroupMappingParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a SCIM group-to-workspace role mapping. Creating a mapping that already exists with the same role succeeds and re-applies the mapping to the group members. Requesting a different role for an existing mapping returns 409. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_SCIM_GROUP_MAPPING, "/scim/group-mappings", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_scim_group_mapping(self, id: str, *, params: _T.GetScimGroupMappingParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetScimGroupMapping200, _Errors]: ...
    @_t.overload
    def get_scim_group_mapping(self, id: str, *, params: _T.GetScimGroupMappingParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetScimGroupMapping200, _HttpClientResponse], _Errors]: ...
    def get_scim_group_mapping(self, id: str, *, params: _T.GetScimGroupMappingParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a SCIM group-to-workspace mapping. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_SCIM_GROUP_MAPPING, _c.encoded_path("/scim/group-mappings/{}", id), params, None, include_response)

    @_t.overload
    def delete_scim_group_mapping(self, id: str, *, params: _T.DeleteScimGroupMappingParams, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteScimGroupMapping200, _Errors]: ...
    @_t.overload
    def delete_scim_group_mapping(self, id: str, *, params: _T.DeleteScimGroupMappingParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteScimGroupMapping200, _HttpClientResponse], _Errors]: ...
    def delete_scim_group_mapping(self, id: str, *, params: _T.DeleteScimGroupMappingParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a SCIM group-to-workspace mapping. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_SCIM_GROUP_MAPPING, _c.encoded_path("/scim/group-mappings/{}", id), params, None, include_response)

    @_t.overload
    def update_scim_group_mapping(self, id: str, *, payload: _T.UpdateScimGroupMappingRequestJson, params: _T.UpdateScimGroupMappingParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateScimGroupMapping200, _Errors]: ...
    @_t.overload
    def update_scim_group_mapping(self, id: str, *, payload: _T.UpdateScimGroupMappingRequestJson, params: _T.UpdateScimGroupMappingParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateScimGroupMapping200, _HttpClientResponse], _Errors]: ...
    def update_scim_group_mapping(self, id: str, *, payload: _T.UpdateScimGroupMappingRequestJson, params: _T.UpdateScimGroupMappingParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update a SCIM group mapping role. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_SCIM_GROUP_MAPPING, _c.encoded_path("/scim/group-mappings/{}", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_scim_groups(self, *, params: _T.ListScimGroupsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListScimGroups200, _Errors]: ...
    @_t.overload
    def list_scim_groups(self, *, params: _T.ListScimGroupsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListScimGroups200, _HttpClientResponse], _Errors]: ...
    def list_scim_groups(self, *, params: _T.ListScimGroupsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List SCIM groups for the organization. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_SCIM_GROUPS, "/scim/groups", params, None, include_response)

    @_t.overload
    def create_scim_sync_job(self, *, params: _T.CreateScimSyncJobParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateScimSyncJob202, _Errors]: ...
    @_t.overload
    def create_scim_sync_job(self, *, params: _T.CreateScimSyncJobParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateScimSyncJob202, _HttpClientResponse], _Errors]: ...
    def create_scim_sync_job(self, *, params: _T.CreateScimSyncJobParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Start a SCIM directory sync. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_SCIM_SYNC_JOB, "/scim/sync-jobs", params, None, include_response)

    @_t.overload
    def get_scim_sync_job(self, id: str, *, params: _T.GetScimSyncJobParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetScimSyncJob200, _Errors]: ...
    @_t.overload
    def get_scim_sync_job(self, id: str, *, params: _T.GetScimSyncJobParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetScimSyncJob200, _HttpClientResponse], _Errors]: ...
    def get_scim_sync_job(self, id: str, *, params: _T.GetScimSyncJobParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get SCIM directory sync status. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_SCIM_SYNC_JOB, _c.encoded_path("/scim/sync-jobs/{}", id), params, None, include_response)

    @_t.overload
    def create_systemone(self, *, payload: _T.CreateSystemoneRequestJson, params: _T.CreateSystemoneParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateSystemone200, _Errors]: ...
    @_t.overload
    def create_systemone(self, *, payload: _T.CreateSystemoneRequestJson, params: _T.CreateSystemoneParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateSystemone200, _HttpClientResponse], _Errors]: ...
    def create_systemone(self, *, payload: _T.CreateSystemoneRequestJson, params: _T.CreateSystemoneParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Sends state and typed questions to a System One model such as Jev and returns its answers. Compatible with the TypeSafe SDKs. Bare System One model IDs such as `jev-1.13` and `jev-latest` are mapped onto the `typesafe/` namespace."""
        return self._json(_CREATE_SYSTEMONE, "/systemone", params, _c.json_body(payload), include_response)

    @_t.overload
    def list_tools(self, *, params: _T.ListToolsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListTools200, _Errors]: ...
    @_t.overload
    def list_tools(self, *, params: _T.ListToolsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListTools200, _HttpClientResponse], _Errors]: ...
    def list_tools(self, *, params: _T.ListToolsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists every server tool OpenRouter can run on behalf of a model: accepted `tools[].type` spellings per API format, the engines behind it with their pricing, and how many endpoints run it natively."""
        return self._json(_LIST_TOOLS, "/tools", params, None, include_response)

    @_t.overload
    def get_tool(self, name: str, *, params: _T.GetToolParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetTool200 | None, _Errors]: ...
    @_t.overload
    def get_tool(self, name: str, *, params: _T.GetToolParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetTool200 | None, _HttpClientResponse], _Errors]: ...
    def get_tool(self, name: str, *, params: _T.GetToolParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """One server tool by canonical name or any accepted alias, with the models that run it natively."""
        return self._json(_GET_TOOL, _c.encoded_path("/tools/{}", name), params, None, include_response)

    @_t.overload
    def list_intern_connections(self, intern_id: str, *, params: _T.ListInternConnectionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListInternConnections200, _Errors]: ...
    @_t.overload
    def list_intern_connections(self, intern_id: str, *, params: _T.ListInternConnectionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListInternConnections200, _HttpClientResponse], _Errors]: ...
    def list_intern_connections(self, intern_id: str, *, params: _T.ListInternConnectionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the connections in scope for the intern, by the key of their card on the dashboard's Connections tab: `github`, `slack`, `google`, a catalog MCP server such as `linear` or `notion`, or `mcp:<host>` for a custom MCP server. A connection is listed when it is stored, enabled, and not turned off or hidden for this intern, as the Connections tab lists it; whether its last test passed is not part of the rule. `ori features add` checks a feature's `ori.requires.connections` against this list. `routing` is the vault's routing table for the intern: the credentials it holds and what it would inject each for, from the same lookups the egress proxy picks a credential with, GitHub repository coverage read through the installation token and cached. `routing_text` is that table as the lines the intern reads in its instructions. Never credentials. Returns 404 for an intern the key cannot see. The scope is selected by the API key: workspace routes act on the key's active workspace and intern routes act on one intern inside that workspace. There is no default workspace and no fallback to another scope. Every vault route, including reads, requires access to the Intern API programme and returns 404 outside it. An intern's own API key is confined to that intern: it can always read the intern's secrets and effective secrets, writes to them follow the rules above, and every other intern and every workspace route answers 404. Requests on regional hostnames such as `eu.openrouter.ai` are refused. [API key](https://openrouter.ai/docs/api-reference/authentication) required."""
        return self._json(_LIST_INTERN_CONNECTIONS, _c.encoded_path("/vault/interns/{}/connections", intern_id), params, None, include_response)

    @_t.overload
    def list_intern_effective_vault_secrets(self, intern_id: str, *, params: _T.ListInternEffectiveVaultSecretsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListInternEffectiveVaultSecrets200, _Errors]: ...
    @_t.overload
    def list_intern_effective_vault_secrets(self, intern_id: str, *, params: _T.ListInternEffectiveVaultSecretsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListInternEffectiveVaultSecrets200, _HttpClientResponse], _Errors]: ...
    def list_intern_effective_vault_secrets(self, intern_id: str, *, params: _T.ListInternEffectiveVaultSecretsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists, one entry per name, the secret the intern's outbound requests receive: its own secrets, secrets from an attached vault, and workspace secrets, including ones stored before workspace-scoped storage. Where several vaults hold a name, the entry is the one that wins, in the order intern, attached, workspace. The same resolution decides what outbound requests receive, so this list and the intern's requests agree. `scope` says which vault the entry comes from. Responses carry metadata only, never values. Results are ordered by name and paginated with `limit` and `offset`. Returns 404 when the intern's attached vault is no longer available, since the intern then receives no secrets. The scope is selected by the API key: workspace routes act on the key's active workspace and intern routes act on one intern inside that workspace. There is no default workspace and no fallback to another scope. Every vault route, including reads, requires access to the Intern API programme and returns 404 outside it. An intern's own API key is confined to that intern: it can always read the intern's secrets and effective secrets, writes to them follow the rules above, and every other intern and every workspace route answers 404. Requests on regional hostnames such as `eu.openrouter.ai` are refused. [API key](https://openrouter.ai/docs/api-reference/authentication) required."""
        return self._json(_LIST_INTERN_EFFECTIVE_VAULT_SECRETS, _c.encoded_path("/vault/interns/{}/effective-secrets", intern_id), params, None, include_response)

    @_t.overload
    def list_intern_vault_secrets(self, intern_id: str, *, params: _T.ListInternVaultSecretsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListInternVaultSecrets200, _Errors]: ...
    @_t.overload
    def list_intern_vault_secrets(self, intern_id: str, *, params: _T.ListInternVaultSecretsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListInternVaultSecrets200, _HttpClientResponse], _Errors]: ...
    def list_intern_vault_secrets(self, intern_id: str, *, params: _T.ListInternVaultSecretsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists secret metadata stored for one intern. The list includes secrets stored from the dashboard or at provisioning before workspace-scoped storage; where both exist under one name, the one stored through this API is listed. Those older secrets cannot be deleted or copied through this API, and storing the same name through this API replaces them. Responses contain names, bound hosts, fingerprints and creation times, never secret values. Results are ordered by name and paginated with `limit` and `offset`. The scope is selected by the API key: workspace routes act on the key's active workspace and intern routes act on one intern inside that workspace. There is no default workspace and no fallback to another scope. Every vault route, including reads, requires access to the Intern API programme and returns 404 outside it. An intern's own API key is confined to that intern: it can always read the intern's secrets and effective secrets, writes to them follow the rules above, and every other intern and every workspace route answers 404. Requests on regional hostnames such as `eu.openrouter.ai` are refused. [API key](https://openrouter.ai/docs/api-reference/authentication) required."""
        return self._json(_LIST_INTERN_VAULT_SECRETS, _c.encoded_path("/vault/interns/{}/secrets", intern_id), params, None, include_response)

    @_t.overload
    def store_intern_vault_secret(self, intern_id: str, name: str, *, payload: _T.StoreInternVaultSecretRequestJson, params: _T.StoreInternVaultSecretParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.StoreInternVaultSecret200, _Errors]: ...
    @_t.overload
    def store_intern_vault_secret(self, intern_id: str, name: str, *, payload: _T.StoreInternVaultSecretRequestJson, params: _T.StoreInternVaultSecretParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.StoreInternVaultSecret200, _HttpClientResponse], _Errors]: ...
    def store_intern_vault_secret(self, intern_id: str, name: str, *, payload: _T.StoreInternVaultSecretRequestJson, params: _T.StoreInternVaultSecretParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates or replaces a secret stored for one intern. The value is encrypted at rest and released only to the exact hostnames in `hosts`. The response carries metadata only. Writes return 503 while vault writes are disabled for the caller. The scope is selected by the API key: workspace routes act on the key's active workspace and intern routes act on one intern inside that workspace. There is no default workspace and no fallback to another scope. Every vault route, including reads, requires access to the Intern API programme and returns 404 outside it. An intern's own API key is confined to that intern: it can always read the intern's secrets and effective secrets, writes to them follow the rules above, and every other intern and every workspace route answers 404. Requests on regional hostnames such as `eu.openrouter.ai` are refused. [API key](https://openrouter.ai/docs/api-reference/authentication) required."""
        return self._json(_STORE_INTERN_VAULT_SECRET, _c.encoded_path("/vault/interns/{}/secrets/{}", intern_id, name), params, _c.json_body(payload), include_response)

    @_t.overload
    def delete_intern_vault_secret(self, intern_id: str, name: str, *, params: _T.DeleteInternVaultSecretParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def delete_intern_vault_secret(self, intern_id: str, name: str, *, params: _T.DeleteInternVaultSecretParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def delete_intern_vault_secret(self, intern_id: str, name: str, *, params: _T.DeleteInternVaultSecretParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a secret stored for one intern. Returns 204 with no body on success and 404 when the secret does not exist in the selected scope. Writes return 503 while vault writes are disabled for the caller. The scope is selected by the API key: workspace routes act on the key's active workspace and intern routes act on one intern inside that workspace. There is no default workspace and no fallback to another scope. Every vault route, including reads, requires access to the Intern API programme and returns 404 outside it. An intern's own API key is confined to that intern: it can always read the intern's secrets and effective secrets, writes to them follow the rules above, and every other intern and every workspace route answers 404. Requests on regional hostnames such as `eu.openrouter.ai` are refused. [API key](https://openrouter.ai/docs/api-reference/authentication) required."""
        return self._json(_DELETE_INTERN_VAULT_SECRET, _c.encoded_path("/vault/interns/{}/secrets/{}", intern_id, name), params, None, include_response)

    @_t.overload
    def copy_vault_secrets_to_intern(self, intern_id: str, *, payload: _T.CopyVaultSecretsToInternRequestJson, params: _T.CopyVaultSecretsToInternParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CopyVaultSecretsToIntern200, _Errors]: ...
    @_t.overload
    def copy_vault_secrets_to_intern(self, intern_id: str, *, payload: _T.CopyVaultSecretsToInternRequestJson, params: _T.CopyVaultSecretsToInternParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CopyVaultSecretsToIntern200, _HttpClientResponse], _Errors]: ...
    def copy_vault_secrets_to_intern(self, intern_id: str, *, payload: _T.CopyVaultSecretsToInternRequestJson, params: _T.CopyVaultSecretsToInternParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Copies the named workspace secrets into one intern's scope, replacing any intern secret with the same name. Each copy keeps the source value and host bindings. Every name must exist in the workspace scope or the request fails with 404 and nothing is copied. A workspace secret whose `hosts` is `null` cannot be copied: the request fails with 409 and nothing is copied until that secret is stored again with hosts. The response carries metadata only. Writes return 503 while vault writes are disabled for the caller. The scope is selected by the API key: workspace routes act on the key's active workspace and intern routes act on one intern inside that workspace. There is no default workspace and no fallback to another scope. Every vault route, including reads, requires access to the Intern API programme and returns 404 outside it. An intern's own API key is confined to that intern: it can always read the intern's secrets and effective secrets, writes to them follow the rules above, and every other intern and every workspace route answers 404. Requests on regional hostnames such as `eu.openrouter.ai` are refused. [API key](https://openrouter.ai/docs/api-reference/authentication) required."""
        return self._json(_COPY_VAULT_SECRETS_TO_INTERN, _c.encoded_path("/vault/interns/{}/secrets/copy", intern_id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_vault_secrets(self, *, params: _T.ListVaultSecretsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListVaultSecrets200, _Errors]: ...
    @_t.overload
    def list_vault_secrets(self, *, params: _T.ListVaultSecretsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListVaultSecrets200, _HttpClientResponse], _Errors]: ...
    def list_vault_secrets(self, *, params: _T.ListVaultSecretsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists secret metadata for the workspace of the authenticated API key. The list includes secrets stored from the dashboard or at provisioning before workspace-scoped storage; where both exist under one name, the one stored through this API is listed. Those older secrets cannot be deleted or copied through this API, and storing the same name through this API replaces them. Responses contain names, bound hosts, fingerprints and creation times, never secret values. Results are ordered by name and paginated with `limit` and `offset`. The scope is selected by the API key: workspace routes act on the key's active workspace and intern routes act on one intern inside that workspace. There is no default workspace and no fallback to another scope. Every vault route, including reads, requires access to the Intern API programme and returns 404 outside it. An intern's own API key is confined to that intern: it can always read the intern's secrets and effective secrets, writes to them follow the rules above, and every other intern and every workspace route answers 404. Requests on regional hostnames such as `eu.openrouter.ai` are refused. [API key](https://openrouter.ai/docs/api-reference/authentication) required."""
        return self._json(_LIST_VAULT_SECRETS, "/vault/secrets", params, None, include_response)

    @_t.overload
    def store_vault_secret(self, name: str, *, payload: _T.StoreVaultSecretRequestJson, params: _T.StoreVaultSecretParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.StoreVaultSecret200, _Errors]: ...
    @_t.overload
    def store_vault_secret(self, name: str, *, payload: _T.StoreVaultSecretRequestJson, params: _T.StoreVaultSecretParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.StoreVaultSecret200, _HttpClientResponse], _Errors]: ...
    def store_vault_secret(self, name: str, *, payload: _T.StoreVaultSecretRequestJson, params: _T.StoreVaultSecretParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates or replaces a secret in the workspace of the authenticated API key. The value is encrypted at rest and released only to the exact hostnames in `hosts`. The response carries metadata only. Writes return 503 while vault writes are disabled for the caller. The scope is selected by the API key: workspace routes act on the key's active workspace and intern routes act on one intern inside that workspace. There is no default workspace and no fallback to another scope. Every vault route, including reads, requires access to the Intern API programme and returns 404 outside it. An intern's own API key is confined to that intern: it can always read the intern's secrets and effective secrets, writes to them follow the rules above, and every other intern and every workspace route answers 404. Requests on regional hostnames such as `eu.openrouter.ai` are refused. [API key](https://openrouter.ai/docs/api-reference/authentication) required."""
        return self._json(_STORE_VAULT_SECRET, _c.encoded_path("/vault/secrets/{}", name), params, _c.json_body(payload), include_response)

    @_t.overload
    def delete_vault_secret(self, name: str, *, params: _T.DeleteVaultSecretParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def delete_vault_secret(self, name: str, *, params: _T.DeleteVaultSecretParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def delete_vault_secret(self, name: str, *, params: _T.DeleteVaultSecretParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a secret from the workspace of the authenticated API key. Returns 204 with no body on success and 404 when the secret does not exist in the selected scope. Writes return 503 while vault writes are disabled for the caller. The scope is selected by the API key: workspace routes act on the key's active workspace and intern routes act on one intern inside that workspace. There is no default workspace and no fallback to another scope. Every vault route, including reads, requires access to the Intern API programme and returns 404 outside it. An intern's own API key is confined to that intern: it can always read the intern's secrets and effective secrets, writes to them follow the rules above, and every other intern and every workspace route answers 404. Requests on regional hostnames such as `eu.openrouter.ai` are refused. [API key](https://openrouter.ai/docs/api-reference/authentication) required."""
        return self._json(_DELETE_VAULT_SECRET, _c.encoded_path("/vault/secrets/{}", name), params, None, include_response)

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
        return self._json(_GET_VIDEOS, _c.encoded_path("/videos/{}", job_id), params, None, include_response)

    @_t.overload
    def list_videos_content(self, job_id: str, *, params: _T.ListVideosContentParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def list_videos_content(self, job_id: str, *, params: _T.ListVideosContentParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def list_videos_content(self, job_id: str, *, params: _T.ListVideosContentParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Streams the generated video content from the upstream provider"""
        return self._json(_LIST_VIDEOS_CONTENT, _c.encoded_path("/videos/{}/content", job_id), params, None, include_response)

    def list_videos_content_stream(self, job_id: str, *, params: _T.ListVideosContentParams | None = None) -> _Stream[bytes, _HttpClientError]:
        """Streams the generated video content from the upstream provider"""
        return self._binary(_LIST_VIDEOS_CONTENT_STREAM, _c.encoded_path("/videos/{}/content", job_id), params, None)

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
        """List all workspaces for the authenticated user. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_WORKSPACES, "/workspaces", params, None, include_response)

    @_t.overload
    def create_workspace(self, *, payload: _T.CreateWorkspaceRequestJson, params: _T.CreateWorkspaceParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateWorkspace201, _Errors]: ...
    @_t.overload
    def create_workspace(self, *, payload: _T.CreateWorkspaceRequestJson, params: _T.CreateWorkspaceParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateWorkspace201, _HttpClientResponse], _Errors]: ...
    def create_workspace(self, *, payload: _T.CreateWorkspaceRequestJson, params: _T.CreateWorkspaceParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new workspace for the authenticated user. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_CREATE_WORKSPACE, "/workspaces", params, _c.json_body(payload), include_response)

    @_t.overload
    def get_workspace(self, id: str, *, params: _T.GetWorkspaceParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetWorkspace200, _Errors]: ...
    @_t.overload
    def get_workspace(self, id: str, *, params: _T.GetWorkspaceParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetWorkspace200, _HttpClientResponse], _Errors]: ...
    def get_workspace(self, id: str, *, params: _T.GetWorkspaceParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a single workspace by ID or slug. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_WORKSPACE, _c.encoded_path("/workspaces/{}", id), params, None, include_response)

    @_t.overload
    def delete_workspace(self, id: str, *, params: _T.DeleteWorkspaceParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteWorkspace200, _Errors]: ...
    @_t.overload
    def delete_workspace(self, id: str, *, params: _T.DeleteWorkspaceParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteWorkspace200, _HttpClientResponse], _Errors]: ...
    def delete_workspace(self, id: str, *, params: _T.DeleteWorkspaceParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an existing workspace. Workspaces with active API keys cannot be deleted; remove the keys first. Deleting the default workspace requires confirm_default_workspace_deletion=true. Deleting any workspace permanently deletes its budgets and guardrails and disables its classifiers and broadcast destinations. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_WORKSPACE, _c.encoded_path("/workspaces/{}", id), params, None, include_response)

    @_t.overload
    def update_workspace(self, id: str, *, payload: _T.UpdateWorkspaceRequestJson, params: _T.UpdateWorkspaceParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateWorkspace200, _Errors]: ...
    @_t.overload
    def update_workspace(self, id: str, *, payload: _T.UpdateWorkspaceRequestJson, params: _T.UpdateWorkspaceParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateWorkspace200, _HttpClientResponse], _Errors]: ...
    def update_workspace(self, id: str, *, payload: _T.UpdateWorkspaceRequestJson, params: _T.UpdateWorkspaceParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update an existing workspace by ID or slug. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPDATE_WORKSPACE, _c.encoded_path("/workspaces/{}", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_workspace_members(self, id: str, *, params: _T.ListWorkspaceMembersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListWorkspaceMembers200, _Errors]: ...
    @_t.overload
    def list_workspace_members(self, id: str, *, params: _T.ListWorkspaceMembersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListWorkspaceMembers200, _HttpClientResponse], _Errors]: ...
    def list_workspace_members(self, id: str, *, params: _T.ListWorkspaceMembersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all members of a workspace. Returns paginated results. For the default workspace, returns all organization members (implicit membership). [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_WORKSPACE_MEMBERS, _c.encoded_path("/workspaces/{}/members", id), params, None, include_response)

    @_t.overload
    def bulk_add_workspace_members(self, id: str, *, payload: _T.BulkAddWorkspaceMembersRequestJson, params: _T.BulkAddWorkspaceMembersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkAddWorkspaceMembers200, _Errors]: ...
    @_t.overload
    def bulk_add_workspace_members(self, id: str, *, payload: _T.BulkAddWorkspaceMembersRequestJson, params: _T.BulkAddWorkspaceMembersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkAddWorkspaceMembers200, _HttpClientResponse], _Errors]: ...
    def bulk_add_workspace_members(self, id: str, *, payload: _T.BulkAddWorkspaceMembersRequestJson, params: _T.BulkAddWorkspaceMembersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Add multiple organization members to a workspace. Members are assigned the same role they hold in the organization. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_ADD_WORKSPACE_MEMBERS, _c.encoded_path("/workspaces/{}/members/add", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def bulk_remove_workspace_members(self, id: str, *, payload: _T.BulkRemoveWorkspaceMembersRequestJson, params: _T.BulkRemoveWorkspaceMembersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BulkRemoveWorkspaceMembers200, _Errors]: ...
    @_t.overload
    def bulk_remove_workspace_members(self, id: str, *, payload: _T.BulkRemoveWorkspaceMembersRequestJson, params: _T.BulkRemoveWorkspaceMembersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BulkRemoveWorkspaceMembers200, _HttpClientResponse], _Errors]: ...
    def bulk_remove_workspace_members(self, id: str, *, payload: _T.BulkRemoveWorkspaceMembersRequestJson, params: _T.BulkRemoveWorkspaceMembersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Remove multiple members from a workspace. Members with active API keys in the workspace cannot be removed. SCIM-managed members cannot be removed; changes must be made in your identity provider. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_BULK_REMOVE_WORKSPACE_MEMBERS, _c.encoded_path("/workspaces/{}/members/remove", id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_workspace_budgets(self, workspace_ref: str, *, params: _T.ListWorkspaceBudgetsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListWorkspaceBudgets200, _Errors]: ...
    @_t.overload
    def list_workspace_budgets(self, workspace_ref: str, *, params: _T.ListWorkspaceBudgetsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListWorkspaceBudgets200, _HttpClientResponse], _Errors]: ...
    def list_workspace_budgets(self, workspace_ref: str, *, params: _T.ListWorkspaceBudgetsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all budgets configured for a workspace. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_LIST_WORKSPACE_BUDGETS, _c.encoded_path("/workspaces/{}/budgets", workspace_ref), params, None, include_response)

    @_t.overload
    def get_workspace_budget(self, workspace_ref: str, interval: str, *, params: _T.GetWorkspaceBudgetParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetWorkspaceBudget200, _Errors]: ...
    @_t.overload
    def get_workspace_budget(self, workspace_ref: str, interval: str, *, params: _T.GetWorkspaceBudgetParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetWorkspaceBudget200, _HttpClientResponse], _Errors]: ...
    def get_workspace_budget(self, workspace_ref: str, interval: str, *, params: _T.GetWorkspaceBudgetParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieve the budget for a given interval. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_GET_WORKSPACE_BUDGET, _c.encoded_path("/workspaces/{}/budgets/{}", workspace_ref, interval), params, None, include_response)

    @_t.overload
    def upsert_workspace_budget(self, workspace_ref: str, interval: str, *, payload: _T.UpsertWorkspaceBudgetRequestJson, params: _T.UpsertWorkspaceBudgetParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.UpsertWorkspaceBudget200, _Errors]: ...
    @_t.overload
    def upsert_workspace_budget(self, workspace_ref: str, interval: str, *, payload: _T.UpsertWorkspaceBudgetRequestJson, params: _T.UpsertWorkspaceBudgetParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpsertWorkspaceBudget200, _HttpClientResponse], _Errors]: ...
    def upsert_workspace_budget(self, workspace_ref: str, interval: str, *, payload: _T.UpsertWorkspaceBudgetRequestJson, params: _T.UpsertWorkspaceBudgetParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create or update the budget for a given interval. Budget limits must strictly decrease as the interval narrows (lifetime > monthly > weekly > daily). The optional `include_byok_in_budgets` flag is a workspace-wide setting: when provided it applies to every budget interval for the workspace, not just the interval in this request. Note that a change made here is applied to budget enforcement immediately, but an already-open workspace settings page in the web dashboard may keep showing the previous value until it is reloaded. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_UPSERT_WORKSPACE_BUDGET, _c.encoded_path("/workspaces/{}/budgets/{}", workspace_ref, interval), params, _c.json_body(payload), include_response)

    @_t.overload
    def delete_workspace_budget(self, workspace_ref: str, interval: str, *, params: _T.DeleteWorkspaceBudgetParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteWorkspaceBudget200, _Errors]: ...
    @_t.overload
    def delete_workspace_budget(self, workspace_ref: str, interval: str, *, params: _T.DeleteWorkspaceBudgetParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteWorkspaceBudget200, _HttpClientResponse], _Errors]: ...
    def delete_workspace_budget(self, workspace_ref: str, interval: str, *, params: _T.DeleteWorkspaceBudgetParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Remove the budget for a given interval. [Management key](https://openrouter.ai/docs/guides/overview/auth/management-api-keys) required."""
        return self._json(_DELETE_WORKSPACE_BUDGET, _c.encoded_path("/workspaces/{}/budgets/{}", workspace_ref, interval), params, None, include_response)


def make(
    http_client: _HttpClientService[_HttpClientError],
    *,
    transform_client: _c.ClientTransform | None = None,
) -> OpenRouterClient:
    """The client over ``http_client`` (requests carry relative paths:
    prepend the API's URL to the client). ``transform_client`` picks the
    client each operation runs on, per call."""
    return OpenRouterClient(http_client, transform_client)


__all__ = ["OpenRouterClient", "OpenRouterClientError", "make"]
