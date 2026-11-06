"""Effect's generated ``OpenAiClient``: a method per operation of the
OpenAI API, generated from Effect's ``Generated.ts`` by
``scripts/gen_ai_schemas.py``; do not edit.

A JSON operation gives its decoded body (with ``include_response=True``,
the body and the response); a documented error status fails with
``OpenAiClientError`` (``tag`` names the operation and status,
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
from pyfect.ai.openai.generated import types as _T
from pyfect.ai.openai.generated import (
    AcceptLiveSession400,
    AcceptLiveSession404,
    AcceptLiveSession409,
    AcceptLiveSession429,
    AcceptLiveSession503,
    AcceptRealtimeCall404,
    AcceptRealtimeCall409,
    ActivateOrganizationCertificates200,
    ActivateOrganizationCertificates400,
    ActivateOrganizationCertificates403,
    ActivateOrganizationCertificates404,
    ActivateOrganizationCertificates429,
    ActivateOrganizationCertificates500,
    ActivateProjectCertificates200,
    ActivateProjectCertificates400,
    ActivateProjectCertificates403,
    ActivateProjectCertificates404,
    ActivateProjectCertificates429,
    ActivateProjectCertificates500,
    AddGroupUser200,
    AddGroupUser400,
    AddGroupUser403,
    AddGroupUser404,
    AddGroupUser409,
    AddGroupUser429,
    AddProjectGroup200,
    AddProjectGroup400,
    AddProjectGroup403,
    AddProjectGroup404,
    AddProjectGroup429,
    AddProjectGroup500,
    AddUploadPart200,
    AddUploadPart400,
    AddUploadPart404,
    AddUploadPart410,
    AddUploadPart429,
    AddUploadPart500,
    AdminApiKeysCreate200,
    AdminApiKeysCreate400,
    AdminApiKeysCreate403,
    AdminApiKeysCreate404,
    AdminApiKeysDelete200,
    AdminApiKeysDelete403,
    AdminApiKeysDelete404,
    AdminApiKeysGet200,
    AdminApiKeysGet403,
    AdminApiKeysGet404,
    AdminApiKeysList200,
    AdminApiKeysList400,
    AdminApiKeysList403,
    ArchiveProject200,
    ArchiveProject400,
    ArchiveProject403,
    ArchiveProject404,
    ArchiveProject429,
    AssignGroupRole200,
    AssignGroupRole400,
    AssignGroupRole403,
    AssignGroupRole404,
    AssignGroupRole429,
    AssignProjectGroupRole200,
    AssignProjectGroupRole400,
    AssignProjectGroupRole403,
    AssignProjectGroupRole404,
    AssignProjectGroupRole429,
    AssignProjectUserRole200,
    AssignProjectUserRole400,
    AssignProjectUserRole403,
    AssignProjectUserRole404,
    AssignProjectUserRole429,
    AssignUserRole200,
    AssignUserRole400,
    AssignUserRole403,
    AssignUserRole404,
    AssignUserRole429,
    BetaCancelResponse200,
    BetaCancelResponse404,
    BetaCancelResponse429,
    BetaCompactconversation200,
    BetaCompactconversation400,
    BetaCompactconversation429,
    BetaCompactconversation503,
    BetaCreateResponse200,
    BetaCreateResponse200Sse,
    BetaCreateResponse400,
    BetaCreateResponse404,
    BetaCreateResponse429,
    BetaCreateResponse503,
    BetaDeleteResponse200,
    BetaDeleteResponse404,
    BetaDeleteResponse429,
    BetaGetResponse200,
    BetaGetResponse404,
    BetaGetResponse429,
    BetaGetinputtokencounts200,
    BetaGetinputtokencounts400,
    BetaGetinputtokencounts429,
    BetaListInputItems200,
    BetaListInputItems404,
    BetaListInputItems429,
    CancelBatch200,
    CancelBatch400,
    CancelBatch404,
    CancelBatch409,
    CancelBatch429,
    CancelChatSessionMethod200,
    CancelChatSessionMethod400,
    CancelChatSessionMethod404,
    CancelChatSessionMethod429,
    CancelEvalRun200,
    CancelEvalRun429,
    CancelFineTuningJob200,
    CancelFineTuningJob400,
    CancelFineTuningJob404,
    CancelFineTuningJob429,
    CancelResponse200,
    CancelResponse404,
    CancelResponse429,
    CancelRun200,
    CancelRun429,
    CancelUpload200,
    CancelUpload400,
    CancelUpload404,
    CancelUpload410,
    CancelUpload429,
    CancelVectorStoreFileBatch200,
    CancelVectorStoreFileBatch400,
    CancelVectorStoreFileBatch404,
    CancelVectorStoreFileBatch409,
    CancelVectorStoreFileBatch429,
    Compactconversation200,
    Compactconversation400,
    Compactconversation429,
    Compactconversation503,
    CompleteUpload200,
    CompleteUpload400,
    CompleteUpload404,
    CompleteUpload410,
    CompleteUpload429,
    CompleteUpload500,
    CreateAgent201,
    CreateAgent400,
    CreateAgent401,
    CreateAgent403,
    CreateAgent404,
    CreateAgent409,
    CreateAgent500,
    CreateAgent503,
    CreateAgentEnvironment201,
    CreateAgentEnvironment400,
    CreateAgentEnvironment401,
    CreateAgentEnvironment403,
    CreateAgentEnvironment404,
    CreateAgentEnvironment409,
    CreateAgentEnvironment429,
    CreateAgentEnvironment500,
    CreateAgentEnvironment503,
    CreateAgentEnvironmentFile201,
    CreateAgentEnvironmentFile400,
    CreateAgentEnvironmentFile401,
    CreateAgentEnvironmentFile403,
    CreateAgentEnvironmentFile404,
    CreateAgentEnvironmentFile409,
    CreateAgentEnvironmentFile429,
    CreateAgentEnvironmentFile500,
    CreateAgentEnvironmentFile503,
    CreateAgentEnvironmentTemplate201,
    CreateAgentEnvironmentTemplate400,
    CreateAgentEnvironmentTemplate401,
    CreateAgentEnvironmentTemplate403,
    CreateAgentEnvironmentTemplate404,
    CreateAgentEnvironmentTemplate500,
    CreateAgentEnvironmentTemplate503,
    CreateAgentSession201,
    CreateAgentSession201Sse,
    CreateAgentSession400,
    CreateAgentSession401,
    CreateAgentSession403,
    CreateAgentSession404,
    CreateAgentSession409,
    CreateAgentSession429,
    CreateAgentSession500,
    CreateAgentSession503,
    CreateAgentSessionEvents400,
    CreateAgentSessionEvents401,
    CreateAgentSessionEvents403,
    CreateAgentSessionEvents404,
    CreateAgentSessionEvents409,
    CreateAgentSessionEvents500,
    CreateAgentSessionEvents503,
    CreateAssistant200,
    CreateAssistant429,
    CreateBatch200,
    CreateBatch400,
    CreateBatch429,
    CreateBatch500,
    CreateBatch503,
    CreateChatCompletion200,
    CreateChatCompletion200Sse,
    CreateChatCompletion400,
    CreateChatCompletion401,
    CreateChatCompletion404,
    CreateChatCompletion429,
    CreateChatCompletion500,
    CreateChatCompletion503,
    CreateChatSessionMethod200,
    CreateChatSessionMethod400,
    CreateChatSessionMethod404,
    CreateChatSessionMethod429,
    CreateCompletion200,
    CreateCompletion400,
    CreateCompletion401,
    CreateCompletion404,
    CreateCompletion429,
    CreateCompletion500,
    CreateCompletion503,
    CreateContainer200,
    CreateContainer400,
    CreateContainer429,
    CreateContainerFile200,
    CreateContainerFile400,
    CreateContainerFile404,
    CreateContainerFile429,
    CreateConversation200,
    CreateConversation400,
    CreateConversation429,
    CreateConversation500,
    CreateConversationItems200,
    CreateConversationItems400,
    CreateConversationItems404,
    CreateConversationItems429,
    CreateConversationItems500,
    CreateDecision200,
    CreateEmbedding200,
    CreateEmbedding400,
    CreateEmbedding401,
    CreateEmbedding429,
    CreateEmbedding500,
    CreateEmbedding503,
    CreateEval201,
    CreateEval400,
    CreateEval429,
    CreateEvalRun201,
    CreateEvalRun400,
    CreateEvalRun404,
    CreateEvalRun429,
    CreateEvalRun500,
    CreateFile200,
    CreateFile400,
    CreateFile429,
    CreateFile500,
    CreateFineTuningCheckpointPermission200,
    CreateFineTuningCheckpointPermission400,
    CreateFineTuningCheckpointPermission404,
    CreateFineTuningCheckpointPermission429,
    CreateFineTuningJob200,
    CreateFineTuningJob400,
    CreateFineTuningJob429,
    CreateGroup200,
    CreateGroup400,
    CreateGroup403,
    CreateGroup404,
    CreateGroup422,
    CreateGroup429,
    CreateGroup500,
    CreateImage200,
    CreateImage200Sse,
    CreateImage400,
    CreateImage403,
    CreateImage410,
    CreateImage429,
    CreateImage500,
    CreateImage503,
    CreateImageEdit200,
    CreateImageEdit200Sse,
    CreateImageEdit400,
    CreateImageEdit403,
    CreateImageEdit410,
    CreateImageEdit429,
    CreateImageEdit500,
    CreateImageEdit503,
    CreateImageVariation200,
    CreateImageVariation400,
    CreateImageVariation403,
    CreateImageVariation410,
    CreateImageVariation429,
    CreateImageVariation500,
    CreateLive201,
    CreateLive400,
    CreateLive413,
    CreateLive429,
    CreateLive503,
    CreateLive504,
    CreateMessage200,
    CreateMessage429,
    CreateModeration200,
    CreateModeration400,
    CreateModeration403,
    CreateModeration429,
    CreateModeration500,
    CreateModeration503,
    CreateOrganizationSpendAlert200,
    CreateOrganizationSpendAlert400,
    CreateOrganizationSpendAlert403,
    CreateProject200,
    CreateProject201,
    CreateProject400,
    CreateProject403,
    CreateProject429,
    CreateProjectRole200,
    CreateProjectRole400,
    CreateProjectRole403,
    CreateProjectRole404,
    CreateProjectRole429,
    CreateProjectServiceAccount200,
    CreateProjectServiceAccount201,
    CreateProjectServiceAccount400,
    CreateProjectServiceAccount403,
    CreateProjectServiceAccount404,
    CreateProjectServiceAccount429,
    CreateProjectSpendAlert200,
    CreateProjectSpendAlert400,
    CreateProjectSpendAlert403,
    CreateProjectSpendAlert404,
    CreateProjectUser200,
    CreateProjectUser201,
    CreateProjectUser400,
    CreateProjectUser403,
    CreateProjectUser404,
    CreateProjectUser409,
    CreateProjectUser429,
    CreateRealtimeClientSecret200,
    CreateRealtimeClientSecret400,
    CreateRealtimeClientSecret404,
    CreateRealtimeClientSecret500,
    CreateRealtimeSession200,
    CreateRealtimeTranscriptionSession200,
    CreateRealtimeTranslationClientSecret200,
    CreateRealtimeTranslationClientSecret400,
    CreateRealtimeTranslationClientSecret404,
    CreateRealtimeTranslationClientSecret500,
    CreateResponse200,
    CreateResponse200Sse,
    CreateResponse400,
    CreateResponse404,
    CreateResponse429,
    CreateResponse503,
    CreateRole200,
    CreateRole400,
    CreateRole403,
    CreateRole404,
    CreateRole429,
    CreateRun200,
    CreateRun200Sse,
    CreateRun429,
    CreateSkill200,
    CreateSkill400,
    CreateSkill429,
    CreateSkill500,
    CreateSkillVersion200,
    CreateSkillVersion400,
    CreateSkillVersion404,
    CreateSkillVersion429,
    CreateSkillVersion500,
    CreateSpeech200Sse,
    CreateSpeech400,
    CreateSpeech401,
    CreateSpeech429,
    CreateSpeech500,
    CreateSpeech503,
    CreateThread200,
    CreateThread429,
    CreateThreadAndRun200,
    CreateThreadAndRun200Sse,
    CreateThreadAndRun429,
    CreateTranscription200,
    CreateTranscription200Sse,
    CreateTranscription400,
    CreateTranscription401,
    CreateTranscription413,
    CreateTranscription429,
    CreateTranscription500,
    CreateTranscription502,
    CreateTranscription503,
    CreateTranslation200,
    CreateTranslation400,
    CreateTranslation401,
    CreateTranslation413,
    CreateTranslation429,
    CreateTranslation500,
    CreateTranslation502,
    CreateTranslation503,
    CreateUpload200,
    CreateUpload400,
    CreateUpload429,
    CreateVault201,
    CreateVault400,
    CreateVault401,
    CreateVault403,
    CreateVault404,
    CreateVault409,
    CreateVault500,
    CreateVault503,
    CreateVaultCredential201,
    CreateVaultCredential400,
    CreateVaultCredential401,
    CreateVaultCredential403,
    CreateVaultCredential404,
    CreateVaultCredential409,
    CreateVaultCredential500,
    CreateVaultCredential503,
    CreateVectorStore200,
    CreateVectorStore400,
    CreateVectorStore404,
    CreateVectorStore429,
    CreateVectorStoreFile200,
    CreateVectorStoreFile400,
    CreateVectorStoreFile404,
    CreateVectorStoreFile409,
    CreateVectorStoreFile429,
    CreateVectorStoreFile500,
    CreateVectorStoreFileBatch200,
    CreateVectorStoreFileBatch400,
    CreateVectorStoreFileBatch404,
    CreateVectorStoreFileBatch409,
    CreateVectorStoreFileBatch429,
    CreateVectorStoreFileBatch500,
    CreateVideo200,
    CreateVideo400,
    CreateVideo404,
    CreateVideo429,
    CreateVideo500,
    CreateVideo503,
    CreateVideoCharacter200,
    CreateVideoCharacter400,
    CreateVideoCharacter404,
    CreateVideoCharacter500,
    CreateVideoCharacter504,
    CreateVideoEdit200,
    CreateVideoEdit400,
    CreateVideoEdit404,
    CreateVideoEdit429,
    CreateVideoEdit500,
    CreateVideoEdit503,
    CreateVideoExtend200,
    CreateVideoExtend400,
    CreateVideoExtend404,
    CreateVideoExtend429,
    CreateVideoExtend500,
    CreateVideoExtend503,
    CreateVideoRemix200,
    CreateVideoRemix400,
    CreateVideoRemix404,
    CreateVideoRemix429,
    CreateVideoRemix500,
    CreateVideoRemix503,
    CreateVoice200,
    CreateVoice400,
    CreateVoice404,
    CreateVoice500,
    CreateVoiceConsent200,
    CreateVoiceConsent400,
    CreateVoiceConsent404,
    CreateWebhookEndpoint200,
    CreateWebhookEndpoint400,
    CreateanAPIkeyforaserviceaccount200,
    CreateanAPIkeyforaserviceaccount400,
    CreateanAPIkeyforaserviceaccount403,
    CreateanAPIkeyforaserviceaccount404,
    CreateanAPIkeyforaserviceaccount409,
    CreateanAPIkeyforaserviceaccount429,
    Createanexternalstorageconfiguration200,
    Createanexternalstorageconfiguration400,
    Createanexternalstorageconfiguration403,
    Createanexternalstorageconfiguration404,
    Createanexternalstorageconfiguration503,
    Createcontentprovenancecheck200,
    Createcontentprovenancecheck400,
    Createcontentprovenancecheck404,
    Createcontentprovenancecheck429,
    Createcontentprovenancecheck500,
    Createcontentprovenancecheck503,
    DeactivateOrganizationCertificates200,
    DeactivateOrganizationCertificates400,
    DeactivateOrganizationCertificates403,
    DeactivateOrganizationCertificates404,
    DeactivateOrganizationCertificates429,
    DeactivateOrganizationCertificates500,
    DeactivateProjectCertificates200,
    DeactivateProjectCertificates400,
    DeactivateProjectCertificates403,
    DeactivateProjectCertificates404,
    DeactivateProjectCertificates429,
    DeactivateProjectCertificates500,
    DeleteAgent200,
    DeleteAgent400,
    DeleteAgent401,
    DeleteAgent403,
    DeleteAgent404,
    DeleteAgent409,
    DeleteAgent500,
    DeleteAgent503,
    DeleteAgentEnvironmentTemplate200,
    DeleteAgentEnvironmentTemplate400,
    DeleteAgentEnvironmentTemplate401,
    DeleteAgentEnvironmentTemplate403,
    DeleteAgentEnvironmentTemplate404,
    DeleteAgentEnvironmentTemplate409,
    DeleteAgentEnvironmentTemplate500,
    DeleteAgentEnvironmentTemplate503,
    DeleteAgentSession200,
    DeleteAgentSession400,
    DeleteAgentSession401,
    DeleteAgentSession403,
    DeleteAgentSession404,
    DeleteAgentSession409,
    DeleteAgentSession500,
    DeleteAgentSession503,
    DeleteAgentSessionArtifact200,
    DeleteAgentSessionArtifact400,
    DeleteAgentSessionArtifact401,
    DeleteAgentSessionArtifact403,
    DeleteAgentSessionArtifact404,
    DeleteAgentSessionArtifact409,
    DeleteAgentSessionArtifact500,
    DeleteAgentSessionArtifact503,
    DeleteAssistant200,
    DeleteAssistant429,
    DeleteCertificate200,
    DeleteCertificate400,
    DeleteCertificate403,
    DeleteCertificate404,
    DeleteCertificate429,
    DeleteChatCompletion200,
    DeleteChatCompletion404,
    DeleteChatCompletion429,
    DeleteChatCompletion500,
    DeleteContainer200,
    DeleteContainer404,
    DeleteContainer429,
    DeleteContainerFile200,
    DeleteContainerFile404,
    DeleteContainerFile429,
    DeleteConversation200,
    DeleteConversation404,
    DeleteConversation429,
    DeleteConversationItem200,
    DeleteConversationItem400,
    DeleteConversationItem404,
    DeleteConversationItem429,
    DeleteConversationItem500,
    DeleteEval200,
    DeleteEval400,
    DeleteEval404,
    DeleteEval429,
    DeleteEvalRun200,
    DeleteEvalRun400,
    DeleteEvalRun404,
    DeleteEvalRun429,
    DeleteFile200,
    DeleteFile404,
    DeleteFile429,
    DeleteFineTuningCheckpointPermission200,
    DeleteFineTuningCheckpointPermission400,
    DeleteFineTuningCheckpointPermission404,
    DeleteFineTuningCheckpointPermission429,
    DeleteGroup200,
    DeleteGroup400,
    DeleteGroup403,
    DeleteGroup404,
    DeleteGroup429,
    DeleteInvite200,
    DeleteInvite400,
    DeleteInvite403,
    DeleteInvite404,
    DeleteInvite429,
    DeleteMessage200,
    DeleteMessage429,
    DeleteModel200,
    DeleteModel403,
    DeleteModel404,
    DeleteOrganizationSpendAlert200,
    DeleteOrganizationSpendAlert403,
    DeleteOrganizationSpendAlert404,
    DeleteProjectApiKey200,
    DeleteProjectApiKey400,
    DeleteProjectApiKey403,
    DeleteProjectApiKey404,
    DeleteProjectApiKey429,
    DeleteProjectModelPermissions200,
    DeleteProjectModelPermissions400,
    DeleteProjectModelPermissions403,
    DeleteProjectModelPermissions404,
    DeleteProjectModelPermissions429,
    DeleteProjectRole200,
    DeleteProjectRole400,
    DeleteProjectRole403,
    DeleteProjectRole404,
    DeleteProjectRole429,
    DeleteProjectServiceAccount200,
    DeleteProjectServiceAccount400,
    DeleteProjectServiceAccount403,
    DeleteProjectServiceAccount404,
    DeleteProjectServiceAccount429,
    DeleteProjectSpendAlert200,
    DeleteProjectSpendAlert400,
    DeleteProjectSpendAlert403,
    DeleteProjectSpendAlert404,
    DeleteProjectUser200,
    DeleteProjectUser400,
    DeleteProjectUser403,
    DeleteProjectUser404,
    DeleteProjectUser429,
    DeleteResponse200,
    DeleteResponse404,
    DeleteResponse429,
    DeleteRole200,
    DeleteRole400,
    DeleteRole403,
    DeleteRole404,
    DeleteRole429,
    DeleteSkill200,
    DeleteSkill404,
    DeleteSkill429,
    DeleteSkillVersion200,
    DeleteSkillVersion400,
    DeleteSkillVersion404,
    DeleteSkillVersion429,
    DeleteThread200,
    DeleteThread429,
    DeleteThreadMethod200,
    DeleteThreadMethod400,
    DeleteThreadMethod404,
    DeleteThreadMethod429,
    DeleteUser200,
    DeleteUser400,
    DeleteUser403,
    DeleteUser404,
    DeleteUser429,
    DeleteVault200,
    DeleteVault400,
    DeleteVault401,
    DeleteVault403,
    DeleteVault404,
    DeleteVault409,
    DeleteVault500,
    DeleteVault503,
    DeleteVaultCredential200,
    DeleteVaultCredential400,
    DeleteVaultCredential401,
    DeleteVaultCredential403,
    DeleteVaultCredential404,
    DeleteVaultCredential409,
    DeleteVaultCredential500,
    DeleteVaultCredential503,
    DeleteVectorStore200,
    DeleteVectorStore404,
    DeleteVectorStore409,
    DeleteVectorStore429,
    DeleteVectorStoreFile200,
    DeleteVectorStoreFile400,
    DeleteVectorStoreFile404,
    DeleteVectorStoreFile409,
    DeleteVectorStoreFile429,
    DeleteVectorStoreFile500,
    DeleteVideo200,
    DeleteVideo400,
    DeleteVideo404,
    DeleteVideo500,
    DeleteVoiceConsent200,
    DeleteVoiceConsent400,
    DeleteVoiceConsent404,
    DeleteWebhookEndpoint200,
    DeleteWebhookEndpoint400,
    DeleteWebhookEndpoint404,
    Deleteanexternalstorageconfiguration200,
    Deleteanexternalstorageconfiguration400,
    Deleteanexternalstorageconfiguration403,
    Deleteanexternalstorageconfiguration404,
    Deleteorganizationspendlimit200,
    Deleteorganizationspendlimit403,
    Deleteorganizationspendlimit404,
    Deleteprojectspendlimit200,
    Deleteprojectspendlimit400,
    Deleteprojectspendlimit403,
    Deleteprojectspendlimit404,
    DownloadFile400,
    DownloadFile404,
    DownloadFile429,
    DownloadFile500,
    DownloadLiveRecording400,
    DownloadLiveRecording404,
    DownloadLiveRecording429,
    DownloadLiveRecording500,
    DownloadLiveRecording503,
    ForkLiveSession201,
    ForkLiveSession400,
    ForkLiveSession413,
    ForkLiveSession429,
    ForkLiveSession503,
    GetAssistant200,
    GetAssistant429,
    GetCertificate200,
    GetCertificate400,
    GetCertificate403,
    GetCertificate404,
    GetCertificate429,
    GetChatCompletion200,
    GetChatCompletion404,
    GetChatCompletion429,
    GetChatCompletion500,
    GetChatCompletionMessages200,
    GetChatCompletionMessages400,
    GetChatCompletionMessages404,
    GetChatCompletionMessages429,
    GetChatCompletionMessages500,
    GetConversation200,
    GetConversation404,
    GetConversation429,
    GetConversationItem200,
    GetConversationItem404,
    GetConversationItem429,
    GetEval200,
    GetEval404,
    GetEval429,
    GetEvalRun200,
    GetEvalRun400,
    GetEvalRun404,
    GetEvalRun429,
    GetEvalRunOutputItem200,
    GetEvalRunOutputItem400,
    GetEvalRunOutputItem404,
    GetEvalRunOutputItem429,
    GetEvalRunOutputItems200,
    GetEvalRunOutputItems400,
    GetEvalRunOutputItems404,
    GetEvalRunOutputItems429,
    GetEvalRuns200,
    GetEvalRuns400,
    GetEvalRuns404,
    GetEvalRuns429,
    GetMessage200,
    GetMessage429,
    GetResponse200,
    GetResponse404,
    GetResponse429,
    GetRun200,
    GetRun429,
    GetRunStep200,
    GetRunStep429,
    GetSkill200,
    GetSkill404,
    GetSkill429,
    GetSkillContent404,
    GetSkillContent429,
    GetSkillVersion200,
    GetSkillVersion400,
    GetSkillVersion404,
    GetSkillVersion429,
    GetSkillVersionContent400,
    GetSkillVersionContent404,
    GetSkillVersionContent429,
    GetThread200,
    GetThread429,
    GetThreadMethod200,
    GetThreadMethod400,
    GetThreadMethod404,
    GetThreadMethod429,
    GetVectorStore200,
    GetVectorStore404,
    GetVectorStore429,
    GetVectorStoreFile200,
    GetVectorStoreFile404,
    GetVectorStoreFile429,
    GetVectorStoreFile500,
    GetVectorStoreFileBatch200,
    GetVectorStoreFileBatch400,
    GetVectorStoreFileBatch404,
    GetVectorStoreFileBatch429,
    GetVideo200,
    GetVideo400,
    GetVideo404,
    GetVideoCharacter200,
    GetVideoCharacter400,
    GetVideoCharacter404,
    GetVoiceConsent200,
    GetVoiceConsent400,
    GetVoiceConsent404,
    Getanexternalstorageconfiguration200,
    Getanexternalstorageconfiguration400,
    Getanexternalstorageconfiguration403,
    Getanexternalstorageconfiguration404,
    Getinputtokencounts200,
    Getinputtokencounts400,
    Getinputtokencounts429,
    Getorganizationspendlimit200,
    Getorganizationspendlimit403,
    Getorganizationspendlimit404,
    Getprojectsafetyalert200,
    Getprojectsafetyalert400,
    Getprojectsafetyalert404,
    Getprojectsafetyalert429,
    Getprojectsafetyalert503,
    Getprojectspendlimit200,
    Getprojectspendlimit400,
    Getprojectspendlimit403,
    Getprojectspendlimit404,
    Getsafetycase200,
    Getsafetycase400,
    Getsafetycase404,
    Getsafetycase429,
    Getsafetycase500,
    Getsafetycase503,
    HangupLiveSession404,
    HangupRealtimeCall404,
    InviteUser200,
    InviteUser201,
    InviteUser400,
    InviteUser403,
    InviteUser429,
    ListAgentEnvironmentFiles200,
    ListAgentEnvironmentFiles400,
    ListAgentEnvironmentFiles401,
    ListAgentEnvironmentFiles403,
    ListAgentEnvironmentFiles404,
    ListAgentEnvironmentFiles409,
    ListAgentEnvironmentFiles500,
    ListAgentEnvironmentFiles503,
    ListAgentEnvironmentTemplates200,
    ListAgentEnvironmentTemplates400,
    ListAgentEnvironmentTemplates401,
    ListAgentEnvironmentTemplates403,
    ListAgentEnvironmentTemplates404,
    ListAgentEnvironmentTemplates500,
    ListAgentEnvironmentTemplates503,
    ListAgentEnvironments200,
    ListAgentEnvironments400,
    ListAgentEnvironments401,
    ListAgentEnvironments403,
    ListAgentEnvironments404,
    ListAgentEnvironments409,
    ListAgentEnvironments500,
    ListAgentEnvironments503,
    ListAgentSessionArtifacts200,
    ListAgentSessionArtifacts400,
    ListAgentSessionArtifacts401,
    ListAgentSessionArtifacts403,
    ListAgentSessionArtifacts404,
    ListAgentSessionArtifacts409,
    ListAgentSessionArtifacts500,
    ListAgentSessionArtifacts503,
    ListAgentSessionEvents200Sse,
    ListAgentSessionEvents400,
    ListAgentSessionEvents401,
    ListAgentSessionEvents403,
    ListAgentSessionEvents404,
    ListAgentSessionEvents409,
    ListAgentSessionEvents500,
    ListAgentSessionEvents503,
    ListAgentSessionItems200,
    ListAgentSessionItems400,
    ListAgentSessionItems401,
    ListAgentSessionItems403,
    ListAgentSessionItems404,
    ListAgentSessionItems409,
    ListAgentSessionItems500,
    ListAgentSessionItems503,
    ListAgentSessionSubagentItems200,
    ListAgentSessionSubagentItems400,
    ListAgentSessionSubagentItems401,
    ListAgentSessionSubagentItems403,
    ListAgentSessionSubagentItems404,
    ListAgentSessionSubagentItems409,
    ListAgentSessionSubagentItems500,
    ListAgentSessionSubagentItems503,
    ListAgentSessionSubagentTurnItems200,
    ListAgentSessionSubagentTurnItems400,
    ListAgentSessionSubagentTurnItems401,
    ListAgentSessionSubagentTurnItems403,
    ListAgentSessionSubagentTurnItems404,
    ListAgentSessionSubagentTurnItems409,
    ListAgentSessionSubagentTurnItems500,
    ListAgentSessionSubagentTurnItems503,
    ListAgentSessionSubagentTurns200,
    ListAgentSessionSubagentTurns400,
    ListAgentSessionSubagentTurns401,
    ListAgentSessionSubagentTurns403,
    ListAgentSessionSubagentTurns404,
    ListAgentSessionSubagentTurns409,
    ListAgentSessionSubagentTurns500,
    ListAgentSessionSubagentTurns503,
    ListAgentSessionSubagents200,
    ListAgentSessionSubagents400,
    ListAgentSessionSubagents401,
    ListAgentSessionSubagents403,
    ListAgentSessionSubagents404,
    ListAgentSessionSubagents409,
    ListAgentSessionSubagents500,
    ListAgentSessionSubagents503,
    ListAgentSessionTraces200,
    ListAgentSessionTraces400,
    ListAgentSessionTraces401,
    ListAgentSessionTraces403,
    ListAgentSessionTraces404,
    ListAgentSessionTraces409,
    ListAgentSessionTraces500,
    ListAgentSessionTraces503,
    ListAgentSessionTurnItems200,
    ListAgentSessionTurnItems400,
    ListAgentSessionTurnItems401,
    ListAgentSessionTurnItems403,
    ListAgentSessionTurnItems404,
    ListAgentSessionTurnItems409,
    ListAgentSessionTurnItems500,
    ListAgentSessionTurnItems503,
    ListAgentSessionTurns200,
    ListAgentSessionTurns400,
    ListAgentSessionTurns401,
    ListAgentSessionTurns403,
    ListAgentSessionTurns404,
    ListAgentSessionTurns409,
    ListAgentSessionTurns500,
    ListAgentSessionTurns503,
    ListAgentSessions200,
    ListAgentSessions400,
    ListAgentSessions401,
    ListAgentSessions403,
    ListAgentSessions404,
    ListAgentSessions409,
    ListAgentSessions500,
    ListAgentSessions503,
    ListAgents200,
    ListAgents400,
    ListAgents401,
    ListAgents403,
    ListAgents404,
    ListAgents409,
    ListAgents500,
    ListAgents503,
    ListAssistants200,
    ListAssistants429,
    ListAuditLogs200,
    ListAuditLogs400,
    ListAuditLogs404,
    ListAuditLogs429,
    ListBatches200,
    ListBatches400,
    ListBatches404,
    ListBatches429,
    ListChatCompletions200,
    ListChatCompletions400,
    ListChatCompletions429,
    ListChatCompletions500,
    ListContainerFiles200,
    ListContainerFiles404,
    ListContainerFiles429,
    ListContainers200,
    ListContainers404,
    ListContainers429,
    ListConversationItems200,
    ListConversationItems400,
    ListConversationItems404,
    ListConversationItems429,
    ListEvals200,
    ListEvals429,
    ListFiles200,
    ListFiles400,
    ListFiles404,
    ListFiles429,
    ListFilesInVectorStoreBatch200,
    ListFilesInVectorStoreBatch400,
    ListFilesInVectorStoreBatch404,
    ListFilesInVectorStoreBatch429,
    ListFineTuningCheckpointPermissions200,
    ListFineTuningCheckpointPermissions400,
    ListFineTuningCheckpointPermissions429,
    ListFineTuningEvents200,
    ListFineTuningEvents400,
    ListFineTuningEvents404,
    ListFineTuningEvents429,
    ListFineTuningJobCheckpoints200,
    ListFineTuningJobCheckpoints400,
    ListFineTuningJobCheckpoints404,
    ListFineTuningJobCheckpoints429,
    ListGroupRoleAssignments200,
    ListGroupRoleAssignments400,
    ListGroupRoleAssignments403,
    ListGroupRoleAssignments404,
    ListGroupRoleAssignments429,
    ListGroupUsers200,
    ListGroupUsers400,
    ListGroupUsers403,
    ListGroupUsers404,
    ListGroupUsers429,
    ListGroupUsers502,
    ListGroups200,
    ListGroups400,
    ListGroups403,
    ListGroups404,
    ListGroups429,
    ListInputItems200,
    ListInputItems404,
    ListInputItems429,
    ListInvites200,
    ListInvites400,
    ListInvites403,
    ListInvites404,
    ListInvites429,
    ListMessages200,
    ListMessages429,
    ListModels200,
    ListModels403,
    ListOrganizationCertificates200,
    ListOrganizationCertificates400,
    ListOrganizationCertificates403,
    ListOrganizationCertificates429,
    ListOrganizationSpendAlerts200,
    ListOrganizationSpendAlerts400,
    ListOrganizationSpendAlerts403,
    ListOrganizationSpendAlerts404,
    ListPaginatedFineTuningJobs200,
    ListPaginatedFineTuningJobs400,
    ListPaginatedFineTuningJobs429,
    ListProjectApiKeys200,
    ListProjectApiKeys400,
    ListProjectApiKeys403,
    ListProjectApiKeys404,
    ListProjectApiKeys429,
    ListProjectCertificates200,
    ListProjectCertificates400,
    ListProjectCertificates403,
    ListProjectCertificates429,
    ListProjectGroupRoleAssignments200,
    ListProjectGroupRoleAssignments400,
    ListProjectGroupRoleAssignments403,
    ListProjectGroupRoleAssignments404,
    ListProjectGroupRoleAssignments429,
    ListProjectGroups200,
    ListProjectGroups400,
    ListProjectGroups403,
    ListProjectGroups404,
    ListProjectGroups429,
    ListProjectRateLimits200,
    ListProjectRateLimits400,
    ListProjectRateLimits403,
    ListProjectRateLimits404,
    ListProjectRoles200,
    ListProjectRoles400,
    ListProjectRoles403,
    ListProjectRoles404,
    ListProjectRoles429,
    ListProjectServiceAccounts200,
    ListProjectServiceAccounts400,
    ListProjectServiceAccounts403,
    ListProjectServiceAccounts404,
    ListProjectServiceAccounts429,
    ListProjectSpendAlerts200,
    ListProjectSpendAlerts400,
    ListProjectSpendAlerts403,
    ListProjectSpendAlerts404,
    ListProjectUserRoleAssignments200,
    ListProjectUserRoleAssignments400,
    ListProjectUserRoleAssignments403,
    ListProjectUserRoleAssignments404,
    ListProjectUserRoleAssignments429,
    ListProjectUsers200,
    ListProjectUsers400,
    ListProjectUsers403,
    ListProjectUsers404,
    ListProjectUsers429,
    ListProjects200,
    ListProjects400,
    ListProjects403,
    ListProjects404,
    ListProjects429,
    ListRoles200,
    ListRoles400,
    ListRoles403,
    ListRoles404,
    ListRoles429,
    ListRunSteps200,
    ListRunSteps429,
    ListRuns200,
    ListRuns429,
    ListSkillVersions200,
    ListSkillVersions400,
    ListSkillVersions404,
    ListSkillVersions429,
    ListSkills200,
    ListSkills404,
    ListSkills429,
    ListThreadItemsMethod200,
    ListThreadItemsMethod400,
    ListThreadItemsMethod404,
    ListThreadItemsMethod429,
    ListThreadsMethod200,
    ListThreadsMethod400,
    ListThreadsMethod404,
    ListThreadsMethod429,
    ListUserRoleAssignments200,
    ListUserRoleAssignments400,
    ListUserRoleAssignments403,
    ListUserRoleAssignments404,
    ListUserRoleAssignments429,
    ListUsers200,
    ListUsers400,
    ListUsers403,
    ListUsers429,
    ListVaultCredentials200,
    ListVaultCredentials400,
    ListVaultCredentials401,
    ListVaultCredentials403,
    ListVaultCredentials404,
    ListVaultCredentials409,
    ListVaultCredentials500,
    ListVaultCredentials503,
    ListVaults200,
    ListVaults400,
    ListVaults401,
    ListVaults403,
    ListVaults404,
    ListVaults409,
    ListVaults500,
    ListVaults503,
    ListVectorStoreFiles200,
    ListVectorStoreFiles400,
    ListVectorStoreFiles404,
    ListVectorStoreFiles429,
    ListVectorStores200,
    ListVectorStores429,
    ListVectorStores503,
    ListVideos200,
    ListVideos400,
    ListVideos404,
    ListVoiceConsents200,
    ListVoiceConsents400,
    ListVoiceConsents404,
    ListWebhookEndpoints200,
    ListWebhookEndpoints400,
    ListWebhookEndpoints404,
    ListWebhookEventTypes200,
    ListWebhookEventTypes401,
    Listexternalstorageconfigurations200,
    Listexternalstorageconfigurations400,
    Listexternalstorageconfigurations403,
    Listexternalstorageconfigurations404,
    ModifyAssistant200,
    ModifyAssistant429,
    ModifyCertificate200,
    ModifyCertificate400,
    ModifyCertificate403,
    ModifyCertificate404,
    ModifyCertificate429,
    ModifyCertificate500,
    ModifyMessage200,
    ModifyMessage429,
    ModifyProject200,
    ModifyProject400,
    ModifyProject403,
    ModifyProject404,
    ModifyProject429,
    ModifyProjectUser200,
    ModifyProjectUser400,
    ModifyProjectUser403,
    ModifyProjectUser404,
    ModifyProjectUser429,
    ModifyRun200,
    ModifyRun429,
    ModifyThread200,
    ModifyThread429,
    ModifyUser200,
    ModifyUser400,
    ModifyUser403,
    ModifyUser404,
    ModifyUser429,
    ModifyVectorStore200,
    ModifyVectorStore400,
    ModifyVectorStore403,
    ModifyVectorStore404,
    ModifyVectorStore429,
    OrganizationDecisionsusage200,
    OrganizationDecisionsusage400,
    OrganizationDecisionsusage403,
    OrganizationDecisionsusage429,
    PauseFineTuningJob200,
    PauseFineTuningJob400,
    PauseFineTuningJob404,
    PauseFineTuningJob429,
    ReferLiveSession400,
    ReferLiveSession404,
    ReferRealtimeCall404,
    RejectLiveSession400,
    RejectLiveSession404,
    RejectLiveSession409,
    RejectRealtimeCall404,
    RejectRealtimeCall409,
    RemoveGroupUser200,
    RemoveGroupUser400,
    RemoveGroupUser403,
    RemoveGroupUser404,
    RemoveGroupUser409,
    RemoveGroupUser429,
    RemoveProjectGroup200,
    RemoveProjectGroup400,
    RemoveProjectGroup403,
    RemoveProjectGroup404,
    RemoveProjectGroup429,
    ResumeFineTuningJob200,
    ResumeFineTuningJob400,
    ResumeFineTuningJob404,
    ResumeFineTuningJob429,
    RetrieveAgent200,
    RetrieveAgent400,
    RetrieveAgent401,
    RetrieveAgent403,
    RetrieveAgent404,
    RetrieveAgent409,
    RetrieveAgent500,
    RetrieveAgent503,
    RetrieveAgentEnvironment200,
    RetrieveAgentEnvironment400,
    RetrieveAgentEnvironment401,
    RetrieveAgentEnvironment403,
    RetrieveAgentEnvironment404,
    RetrieveAgentEnvironment409,
    RetrieveAgentEnvironment500,
    RetrieveAgentEnvironment503,
    RetrieveAgentEnvironmentTemplate200,
    RetrieveAgentEnvironmentTemplate400,
    RetrieveAgentEnvironmentTemplate401,
    RetrieveAgentEnvironmentTemplate403,
    RetrieveAgentEnvironmentTemplate404,
    RetrieveAgentEnvironmentTemplate500,
    RetrieveAgentEnvironmentTemplate503,
    RetrieveAgentSession200,
    RetrieveAgentSession400,
    RetrieveAgentSession401,
    RetrieveAgentSession403,
    RetrieveAgentSession404,
    RetrieveAgentSession409,
    RetrieveAgentSession500,
    RetrieveAgentSession503,
    RetrieveAgentSessionArtifact200,
    RetrieveAgentSessionArtifact400,
    RetrieveAgentSessionArtifact401,
    RetrieveAgentSessionArtifact403,
    RetrieveAgentSessionArtifact404,
    RetrieveAgentSessionArtifact409,
    RetrieveAgentSessionArtifact500,
    RetrieveAgentSessionArtifact503,
    RetrieveAgentSessionArtifactContent400,
    RetrieveAgentSessionArtifactContent401,
    RetrieveAgentSessionArtifactContent403,
    RetrieveAgentSessionArtifactContent404,
    RetrieveAgentSessionArtifactContent409,
    RetrieveAgentSessionArtifactContent500,
    RetrieveAgentSessionArtifactContent503,
    RetrieveAgentSessionSubagent200,
    RetrieveAgentSessionSubagent400,
    RetrieveAgentSessionSubagent401,
    RetrieveAgentSessionSubagent403,
    RetrieveAgentSessionSubagent404,
    RetrieveAgentSessionSubagent409,
    RetrieveAgentSessionSubagent500,
    RetrieveAgentSessionSubagent503,
    RetrieveAgentSessionSubagentTurn200,
    RetrieveAgentSessionSubagentTurn400,
    RetrieveAgentSessionSubagentTurn401,
    RetrieveAgentSessionSubagentTurn403,
    RetrieveAgentSessionSubagentTurn404,
    RetrieveAgentSessionSubagentTurn409,
    RetrieveAgentSessionSubagentTurn500,
    RetrieveAgentSessionSubagentTurn503,
    RetrieveAgentSessionTurn200,
    RetrieveAgentSessionTurn400,
    RetrieveAgentSessionTurn401,
    RetrieveAgentSessionTurn403,
    RetrieveAgentSessionTurn404,
    RetrieveAgentSessionTurn409,
    RetrieveAgentSessionTurn500,
    RetrieveAgentSessionTurn503,
    RetrieveBatch200,
    RetrieveBatch400,
    RetrieveBatch404,
    RetrieveBatch429,
    RetrieveContainer200,
    RetrieveContainer404,
    RetrieveContainer429,
    RetrieveContainerFile200,
    RetrieveContainerFile404,
    RetrieveContainerFile429,
    RetrieveContainerFileContent404,
    RetrieveContainerFileContent429,
    RetrieveFile200,
    RetrieveFile404,
    RetrieveFile429,
    RetrieveFineTuningJob200,
    RetrieveFineTuningJob404,
    RetrieveFineTuningJob429,
    RetrieveGroup200,
    RetrieveGroup400,
    RetrieveGroup403,
    RetrieveGroup404,
    RetrieveGroup429,
    RetrieveGroup500,
    RetrieveGroupRole200,
    RetrieveGroupRole400,
    RetrieveGroupRole403,
    RetrieveGroupRole404,
    RetrieveGroupRole429,
    RetrieveGroupUser200,
    RetrieveGroupUser400,
    RetrieveGroupUser403,
    RetrieveGroupUser404,
    RetrieveGroupUser429,
    RetrieveInvite200,
    RetrieveInvite400,
    RetrieveInvite403,
    RetrieveInvite404,
    RetrieveInvite429,
    RetrieveInvite500,
    RetrieveModel200,
    RetrieveModel403,
    RetrieveModel404,
    RetrieveOrganizationDataRetention200,
    RetrieveOrganizationDataRetention403,
    RetrieveOrganizationDataRetention404,
    RetrieveOrganizationSpendAlert200,
    RetrieveOrganizationSpendAlert403,
    RetrieveOrganizationSpendAlert404,
    RetrieveProject200,
    RetrieveProject403,
    RetrieveProject404,
    RetrieveProject429,
    RetrieveProjectApiKey200,
    RetrieveProjectApiKey400,
    RetrieveProjectApiKey403,
    RetrieveProjectApiKey404,
    RetrieveProjectApiKey429,
    RetrieveProjectDataRetention200,
    RetrieveProjectDataRetention400,
    RetrieveProjectDataRetention403,
    RetrieveProjectDataRetention404,
    RetrieveProjectGroup200,
    RetrieveProjectGroup400,
    RetrieveProjectGroup403,
    RetrieveProjectGroup404,
    RetrieveProjectGroup429,
    RetrieveProjectGroupRole200,
    RetrieveProjectGroupRole400,
    RetrieveProjectGroupRole403,
    RetrieveProjectGroupRole404,
    RetrieveProjectGroupRole429,
    RetrieveProjectHostedToolPermissions200,
    RetrieveProjectHostedToolPermissions400,
    RetrieveProjectHostedToolPermissions403,
    RetrieveProjectHostedToolPermissions404,
    RetrieveProjectHostedToolPermissions429,
    RetrieveProjectModelPermissions200,
    RetrieveProjectModelPermissions400,
    RetrieveProjectModelPermissions403,
    RetrieveProjectModelPermissions404,
    RetrieveProjectModelPermissions429,
    RetrieveProjectRole200,
    RetrieveProjectRole403,
    RetrieveProjectRole404,
    RetrieveProjectRole429,
    RetrieveProjectServiceAccount200,
    RetrieveProjectServiceAccount400,
    RetrieveProjectServiceAccount403,
    RetrieveProjectServiceAccount404,
    RetrieveProjectServiceAccount429,
    RetrieveProjectSpendAlert200,
    RetrieveProjectSpendAlert400,
    RetrieveProjectSpendAlert403,
    RetrieveProjectSpendAlert404,
    RetrieveProjectUser200,
    RetrieveProjectUser400,
    RetrieveProjectUser403,
    RetrieveProjectUser404,
    RetrieveProjectUser429,
    RetrieveProjectUserRole200,
    RetrieveProjectUserRole400,
    RetrieveProjectUserRole403,
    RetrieveProjectUserRole404,
    RetrieveProjectUserRole429,
    RetrieveRole200,
    RetrieveRole403,
    RetrieveRole404,
    RetrieveRole429,
    RetrieveUser200,
    RetrieveUser403,
    RetrieveUser404,
    RetrieveUser429,
    RetrieveUserRole200,
    RetrieveUserRole400,
    RetrieveUserRole403,
    RetrieveUserRole404,
    RetrieveUserRole429,
    RetrieveVault200,
    RetrieveVault400,
    RetrieveVault401,
    RetrieveVault403,
    RetrieveVault404,
    RetrieveVault409,
    RetrieveVault500,
    RetrieveVault503,
    RetrieveVaultCredential200,
    RetrieveVaultCredential400,
    RetrieveVaultCredential401,
    RetrieveVaultCredential403,
    RetrieveVaultCredential404,
    RetrieveVaultCredential409,
    RetrieveVaultCredential500,
    RetrieveVaultCredential503,
    RetrieveVectorStoreFileContent200,
    RetrieveVectorStoreFileContent400,
    RetrieveVectorStoreFileContent404,
    RetrieveVectorStoreFileContent429,
    RetrieveVectorStoreFileContent500,
    RetrieveVideoContent400,
    RetrieveVideoContent404,
    RetrieveVideoContent500,
    RetrieveWebhookEndpoint200,
    RetrieveWebhookEndpoint400,
    RetrieveWebhookEndpoint404,
    RotateVaultCredential200,
    RotateVaultCredential400,
    RotateVaultCredential401,
    RotateVaultCredential403,
    RotateVaultCredential404,
    RotateVaultCredential409,
    RotateVaultCredential500,
    RotateVaultCredential503,
    RotateWebhookEndpointSigningSecret200,
    RotateWebhookEndpointSigningSecret400,
    RotateWebhookEndpointSigningSecret404,
    RunGrader200,
    RunGrader400,
    RunGrader429,
    SearchVectorStore200,
    SearchVectorStore400,
    SearchVectorStore404,
    SearchVectorStore429,
    SubmitToolOuputsToRun200,
    SubmitToolOuputsToRun200Sse,
    SubmitToolOuputsToRun429,
    TestWebhookEndpoint200,
    TestWebhookEndpoint400,
    TestWebhookEndpoint404,
    TestWebhookEndpoint500,
    UnassignGroupRole200,
    UnassignGroupRole400,
    UnassignGroupRole403,
    UnassignGroupRole404,
    UnassignGroupRole429,
    UnassignProjectGroupRole200,
    UnassignProjectGroupRole400,
    UnassignProjectGroupRole403,
    UnassignProjectGroupRole404,
    UnassignProjectGroupRole429,
    UnassignProjectUserRole200,
    UnassignProjectUserRole400,
    UnassignProjectUserRole403,
    UnassignProjectUserRole404,
    UnassignProjectUserRole429,
    UnassignUserRole200,
    UnassignUserRole400,
    UnassignUserRole403,
    UnassignUserRole404,
    UnassignUserRole429,
    UpdateAgent200,
    UpdateAgent400,
    UpdateAgent401,
    UpdateAgent403,
    UpdateAgent404,
    UpdateAgent409,
    UpdateAgent500,
    UpdateAgent503,
    UpdateAgentEnvironmentTemplate200,
    UpdateAgentEnvironmentTemplate400,
    UpdateAgentEnvironmentTemplate401,
    UpdateAgentEnvironmentTemplate403,
    UpdateAgentEnvironmentTemplate404,
    UpdateAgentEnvironmentTemplate409,
    UpdateAgentEnvironmentTemplate500,
    UpdateAgentEnvironmentTemplate503,
    UpdateAgentSession200,
    UpdateAgentSession400,
    UpdateAgentSession401,
    UpdateAgentSession403,
    UpdateAgentSession404,
    UpdateAgentSession409,
    UpdateAgentSession500,
    UpdateAgentSession503,
    UpdateChatCompletion200,
    UpdateChatCompletion400,
    UpdateChatCompletion404,
    UpdateChatCompletion429,
    UpdateChatCompletion500,
    UpdateConversation200,
    UpdateConversation400,
    UpdateConversation404,
    UpdateConversation429,
    UpdateConversation500,
    UpdateEval200,
    UpdateEval400,
    UpdateEval404,
    UpdateEval429,
    UpdateGroup200,
    UpdateGroup400,
    UpdateGroup403,
    UpdateGroup404,
    UpdateGroup429,
    UpdateGroup500,
    UpdateOrganizationDataRetention200,
    UpdateOrganizationDataRetention400,
    UpdateOrganizationDataRetention403,
    UpdateOrganizationDataRetention404,
    UpdateOrganizationSpendAlert200,
    UpdateOrganizationSpendAlert400,
    UpdateOrganizationSpendAlert403,
    UpdateOrganizationSpendAlert404,
    UpdateProjectDataRetention200,
    UpdateProjectDataRetention400,
    UpdateProjectDataRetention403,
    UpdateProjectDataRetention404,
    UpdateProjectHostedToolPermissions200,
    UpdateProjectHostedToolPermissions400,
    UpdateProjectHostedToolPermissions403,
    UpdateProjectHostedToolPermissions404,
    UpdateProjectHostedToolPermissions409,
    UpdateProjectHostedToolPermissions429,
    UpdateProjectModelPermissions200,
    UpdateProjectModelPermissions400,
    UpdateProjectModelPermissions403,
    UpdateProjectModelPermissions404,
    UpdateProjectModelPermissions429,
    UpdateProjectRateLimits200,
    UpdateProjectRateLimits400,
    UpdateProjectRateLimits403,
    UpdateProjectRateLimits404,
    UpdateProjectRole200,
    UpdateProjectRole400,
    UpdateProjectRole403,
    UpdateProjectRole404,
    UpdateProjectRole429,
    UpdateProjectServiceAccount200,
    UpdateProjectServiceAccount400,
    UpdateProjectServiceAccount403,
    UpdateProjectServiceAccount404,
    UpdateProjectServiceAccount429,
    UpdateProjectSpendAlert200,
    UpdateProjectSpendAlert400,
    UpdateProjectSpendAlert403,
    UpdateProjectSpendAlert404,
    UpdateRole200,
    UpdateRole400,
    UpdateRole403,
    UpdateRole404,
    UpdateRole429,
    UpdateSkillDefaultVersion200,
    UpdateSkillDefaultVersion400,
    UpdateSkillDefaultVersion404,
    UpdateSkillDefaultVersion429,
    UpdateVault200,
    UpdateVault400,
    UpdateVault401,
    UpdateVault403,
    UpdateVault404,
    UpdateVault409,
    UpdateVault500,
    UpdateVault503,
    UpdateVectorStoreFileAttributes200,
    UpdateVectorStoreFileAttributes400,
    UpdateVectorStoreFileAttributes404,
    UpdateVectorStoreFileAttributes409,
    UpdateVectorStoreFileAttributes429,
    UpdateVectorStoreFileAttributes500,
    UpdateVoiceConsent200,
    UpdateVoiceConsent400,
    UpdateVoiceConsent404,
    UpdateWebhookEndpoint200,
    UpdateWebhookEndpoint400,
    UpdateWebhookEndpoint404,
    Updateorganizationspendlimit200,
    Updateorganizationspendlimit400,
    Updateorganizationspendlimit403,
    Updateprojectspendlimit200,
    Updateprojectspendlimit400,
    Updateprojectspendlimit403,
    Updateprojectspendlimit404,
    UploadCertificate200,
    UploadCertificate400,
    UploadCertificate403,
    UploadCertificate429,
    UsageAudioSpeeches200,
    UsageAudioSpeeches400,
    UsageAudioSpeeches403,
    UsageAudioSpeeches429,
    UsageAudioTranscriptions200,
    UsageAudioTranscriptions400,
    UsageAudioTranscriptions403,
    UsageAudioTranscriptions429,
    UsageCodeInterpreterSessions200,
    UsageCodeInterpreterSessions400,
    UsageCodeInterpreterSessions403,
    UsageCodeInterpreterSessions429,
    UsageCompletions200,
    UsageCompletions400,
    UsageCompletions403,
    UsageCompletions429,
    UsageCosts200,
    UsageCosts400,
    UsageCosts403,
    UsageCosts429,
    UsageEmbeddings200,
    UsageEmbeddings400,
    UsageEmbeddings403,
    UsageEmbeddings429,
    UsageFileSearchCalls200,
    UsageFileSearchCalls400,
    UsageFileSearchCalls403,
    UsageFileSearchCalls429,
    UsageImages200,
    UsageImages400,
    UsageImages403,
    UsageImages429,
    UsageModerations200,
    UsageModerations400,
    UsageModerations403,
    UsageModerations429,
    UsageVectorStores200,
    UsageVectorStores400,
    UsageVectorStores403,
    UsageVectorStores429,
    UsageWebSearchCalls200,
    UsageWebSearchCalls400,
    UsageWebSearchCalls403,
    UsageWebSearchCalls429,
    ValidateGrader200,
    ValidateGrader400,
    ValidateGrader429,
    Validateanexternalstorageconfiguration200,
    Validateanexternalstorageconfiguration400,
    Validateanexternalstorageconfiguration403,
    Validateanexternalstorageconfiguration404,
    Validateanexternalstorageconfiguration503,
)


class OpenAiClientError(_c.ClientError):
    """A documented error status of an operation."""


type _Errors = _HttpClientError | _S.SchemaError | OpenAiClientError
type _PlainErrors = _HttpClientError | _S.SchemaError
type _SseErrors = _HttpClientError | _S.SchemaError | _sse.Retry | _sse.SseError

_LIST_ASSISTANTS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', ), success=ListAssistants200, errors={429: ('ListAssistants429', ListAssistants429)})
_CREATE_ASSISTANT = _c.Operation("POST", success=CreateAssistant200, errors={429: ('CreateAssistant429', CreateAssistant429)})
_GET_ASSISTANT = _c.Operation("GET", success=GetAssistant200, errors={429: ('GetAssistant429', GetAssistant429)})
_MODIFY_ASSISTANT = _c.Operation("POST", success=ModifyAssistant200, errors={429: ('ModifyAssistant429', ModifyAssistant429)})
_DELETE_ASSISTANT = _c.Operation("DELETE", success=DeleteAssistant200, errors={429: ('DeleteAssistant429', DeleteAssistant429)})
_CREATE_SPEECH = _c.Operation("POST", binary_success=True, errors={400: ('CreateSpeech400', CreateSpeech400), 401: ('CreateSpeech401', CreateSpeech401), 429: ('CreateSpeech429', CreateSpeech429), 500: ('CreateSpeech500', CreateSpeech500), 503: ('CreateSpeech503', CreateSpeech503)})
_CREATE_SPEECH_SSE = _c.Operation("POST")
_CREATE_SPEECH_STREAM = _c.Operation("POST")
_CREATE_TRANSCRIPTION = _c.Operation("POST", success=CreateTranscription200, errors={400: ('CreateTranscription400', CreateTranscription400), 401: ('CreateTranscription401', CreateTranscription401), 413: ('CreateTranscription413', CreateTranscription413), 429: ('CreateTranscription429', CreateTranscription429), 500: ('CreateTranscription500', CreateTranscription500), 502: ('CreateTranscription502', CreateTranscription502), 503: ('CreateTranscription503', CreateTranscription503)})
_CREATE_TRANSCRIPTION_SSE = _c.Operation("POST")
_CREATE_TRANSLATION = _c.Operation("POST", success=CreateTranslation200, errors={400: ('CreateTranslation400', CreateTranslation400), 401: ('CreateTranslation401', CreateTranslation401), 413: ('CreateTranslation413', CreateTranslation413), 429: ('CreateTranslation429', CreateTranslation429), 500: ('CreateTranslation500', CreateTranslation500), 502: ('CreateTranslation502', CreateTranslation502), 503: ('CreateTranslation503', CreateTranslation503)})
_LIST_VOICE_CONSENTS = _c.Operation("GET", url_params=('after', 'limit', ), success=ListVoiceConsents200, errors={400: ('ListVoiceConsents400', ListVoiceConsents400), 404: ('ListVoiceConsents404', ListVoiceConsents404)})
_CREATE_VOICE_CONSENT = _c.Operation("POST", success=CreateVoiceConsent200, errors={400: ('CreateVoiceConsent400', CreateVoiceConsent400), 404: ('CreateVoiceConsent404', CreateVoiceConsent404)})
_GET_VOICE_CONSENT = _c.Operation("GET", success=GetVoiceConsent200, errors={400: ('GetVoiceConsent400', GetVoiceConsent400), 404: ('GetVoiceConsent404', GetVoiceConsent404)})
_UPDATE_VOICE_CONSENT = _c.Operation("POST", success=UpdateVoiceConsent200, errors={400: ('UpdateVoiceConsent400', UpdateVoiceConsent400), 404: ('UpdateVoiceConsent404', UpdateVoiceConsent404)})
_DELETE_VOICE_CONSENT = _c.Operation("DELETE", success=DeleteVoiceConsent200, errors={400: ('DeleteVoiceConsent400', DeleteVoiceConsent400), 404: ('DeleteVoiceConsent404', DeleteVoiceConsent404)})
_CREATE_VOICE = _c.Operation("POST", success=CreateVoice200, errors={400: ('CreateVoice400', CreateVoice400), 404: ('CreateVoice404', CreateVoice404), 500: ('CreateVoice500', CreateVoice500)})
_LIST_BATCHES = _c.Operation("GET", url_params=('after', 'limit', ), success=ListBatches200, errors={400: ('ListBatches400', ListBatches400), 404: ('ListBatches404', ListBatches404), 429: ('ListBatches429', ListBatches429)})
_CREATE_BATCH = _c.Operation("POST", success=CreateBatch200, errors={400: ('CreateBatch400', CreateBatch400), 429: ('CreateBatch429', CreateBatch429), 500: ('CreateBatch500', CreateBatch500), 503: ('CreateBatch503', CreateBatch503)})
_RETRIEVE_BATCH = _c.Operation("GET", success=RetrieveBatch200, errors={400: ('RetrieveBatch400', RetrieveBatch400), 404: ('RetrieveBatch404', RetrieveBatch404), 429: ('RetrieveBatch429', RetrieveBatch429)})
_CANCEL_BATCH = _c.Operation("POST", success=CancelBatch200, errors={400: ('CancelBatch400', CancelBatch400), 404: ('CancelBatch404', CancelBatch404), 409: ('CancelBatch409', CancelBatch409), 429: ('CancelBatch429', CancelBatch429)})
_LIST_CHAT_COMPLETIONS = _c.Operation("GET", url_params=('model', 'metadata', 'after', 'limit', 'order', ), success=ListChatCompletions200, errors={400: ('ListChatCompletions400', ListChatCompletions400), 429: ('ListChatCompletions429', ListChatCompletions429), 500: ('ListChatCompletions500', ListChatCompletions500)})
_CREATE_CHAT_COMPLETION = _c.Operation("POST", success=CreateChatCompletion200, errors={400: ('CreateChatCompletion400', CreateChatCompletion400), 401: ('CreateChatCompletion401', CreateChatCompletion401), 404: ('CreateChatCompletion404', CreateChatCompletion404), 429: ('CreateChatCompletion429', CreateChatCompletion429), 500: ('CreateChatCompletion500', CreateChatCompletion500), 503: ('CreateChatCompletion503', CreateChatCompletion503)})
_CREATE_CHAT_COMPLETION_SSE = _c.Operation("POST")
_GET_CHAT_COMPLETION = _c.Operation("GET", success=GetChatCompletion200, errors={404: ('GetChatCompletion404', GetChatCompletion404), 429: ('GetChatCompletion429', GetChatCompletion429), 500: ('GetChatCompletion500', GetChatCompletion500)})
_UPDATE_CHAT_COMPLETION = _c.Operation("POST", success=UpdateChatCompletion200, errors={400: ('UpdateChatCompletion400', UpdateChatCompletion400), 404: ('UpdateChatCompletion404', UpdateChatCompletion404), 429: ('UpdateChatCompletion429', UpdateChatCompletion429), 500: ('UpdateChatCompletion500', UpdateChatCompletion500)})
_DELETE_CHAT_COMPLETION = _c.Operation("DELETE", success=DeleteChatCompletion200, errors={404: ('DeleteChatCompletion404', DeleteChatCompletion404), 429: ('DeleteChatCompletion429', DeleteChatCompletion429), 500: ('DeleteChatCompletion500', DeleteChatCompletion500)})
_GET_CHAT_COMPLETION_MESSAGES = _c.Operation("GET", url_params=('after', 'limit', 'order', ), success=GetChatCompletionMessages200, errors={400: ('GetChatCompletionMessages400', GetChatCompletionMessages400), 404: ('GetChatCompletionMessages404', GetChatCompletionMessages404), 429: ('GetChatCompletionMessages429', GetChatCompletionMessages429), 500: ('GetChatCompletionMessages500', GetChatCompletionMessages500)})
_CREATE_COMPLETION = _c.Operation("POST", success=CreateCompletion200, errors={400: ('CreateCompletion400', CreateCompletion400), 401: ('CreateCompletion401', CreateCompletion401), 404: ('CreateCompletion404', CreateCompletion404), 429: ('CreateCompletion429', CreateCompletion429), 500: ('CreateCompletion500', CreateCompletion500), 503: ('CreateCompletion503', CreateCompletion503)})
_LIST_CONTAINERS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'name', ), success=ListContainers200, errors={404: ('ListContainers404', ListContainers404), 429: ('ListContainers429', ListContainers429)})
_CREATE_CONTAINER = _c.Operation("POST", success=CreateContainer200, errors={400: ('CreateContainer400', CreateContainer400), 429: ('CreateContainer429', CreateContainer429)})
_RETRIEVE_CONTAINER = _c.Operation("GET", success=RetrieveContainer200, errors={404: ('RetrieveContainer404', RetrieveContainer404), 429: ('RetrieveContainer429', RetrieveContainer429)})
_DELETE_CONTAINER = _c.Operation("DELETE", success=DeleteContainer200, errors={404: ('DeleteContainer404', DeleteContainer404), 429: ('DeleteContainer429', DeleteContainer429)})
_LIST_CONTAINER_FILES = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListContainerFiles200, errors={404: ('ListContainerFiles404', ListContainerFiles404), 429: ('ListContainerFiles429', ListContainerFiles429)})
_CREATE_CONTAINER_FILE = _c.Operation("POST", success=CreateContainerFile200, errors={400: ('CreateContainerFile400', CreateContainerFile400), 404: ('CreateContainerFile404', CreateContainerFile404), 429: ('CreateContainerFile429', CreateContainerFile429)})
_RETRIEVE_CONTAINER_FILE = _c.Operation("GET", success=RetrieveContainerFile200, errors={404: ('RetrieveContainerFile404', RetrieveContainerFile404), 429: ('RetrieveContainerFile429', RetrieveContainerFile429)})
_DELETE_CONTAINER_FILE = _c.Operation("DELETE", success=DeleteContainerFile200, errors={404: ('DeleteContainerFile404', DeleteContainerFile404), 429: ('DeleteContainerFile429', DeleteContainerFile429)})
_RETRIEVE_CONTAINER_FILE_CONTENT = _c.Operation("GET", binary_success=True, errors={404: ('RetrieveContainerFileContent404', RetrieveContainerFileContent404), 429: ('RetrieveContainerFileContent429', RetrieveContainerFileContent429)})
_RETRIEVE_CONTAINER_FILE_CONTENT_STREAM = _c.Operation("GET")
_LIST_CONVERSATION_ITEMS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'include', ), success=ListConversationItems200, errors={400: ('ListConversationItems400', ListConversationItems400), 404: ('ListConversationItems404', ListConversationItems404), 429: ('ListConversationItems429', ListConversationItems429)})
_CREATE_CONVERSATION_ITEMS = _c.Operation("POST", url_params=('include', ), success=CreateConversationItems200, errors={400: ('CreateConversationItems400', CreateConversationItems400), 404: ('CreateConversationItems404', CreateConversationItems404), 429: ('CreateConversationItems429', CreateConversationItems429), 500: ('CreateConversationItems500', CreateConversationItems500)})
_GET_CONVERSATION_ITEM = _c.Operation("GET", url_params=('include', ), success=GetConversationItem200, errors={404: ('GetConversationItem404', GetConversationItem404), 429: ('GetConversationItem429', GetConversationItem429)})
_DELETE_CONVERSATION_ITEM = _c.Operation("DELETE", success=DeleteConversationItem200, errors={400: ('DeleteConversationItem400', DeleteConversationItem400), 404: ('DeleteConversationItem404', DeleteConversationItem404), 429: ('DeleteConversationItem429', DeleteConversationItem429), 500: ('DeleteConversationItem500', DeleteConversationItem500)})
_CREATE_EMBEDDING = _c.Operation("POST", success=CreateEmbedding200, errors={400: ('CreateEmbedding400', CreateEmbedding400), 401: ('CreateEmbedding401', CreateEmbedding401), 429: ('CreateEmbedding429', CreateEmbedding429), 500: ('CreateEmbedding500', CreateEmbedding500), 503: ('CreateEmbedding503', CreateEmbedding503)})
_LIST_EVALS = _c.Operation("GET", url_params=('after', 'limit', 'order', 'order_by', ), success=ListEvals200, errors={429: ('ListEvals429', ListEvals429)})
_CREATE_EVAL = _c.Operation("POST", success=CreateEval201, errors={400: ('CreateEval400', CreateEval400), 429: ('CreateEval429', CreateEval429)})
_GET_EVAL = _c.Operation("GET", success=GetEval200, errors={404: ('GetEval404', GetEval404), 429: ('GetEval429', GetEval429)})
_UPDATE_EVAL = _c.Operation("POST", success=UpdateEval200, errors={400: ('UpdateEval400', UpdateEval400), 404: ('UpdateEval404', UpdateEval404), 429: ('UpdateEval429', UpdateEval429)})
_DELETE_EVAL = _c.Operation("DELETE", success=DeleteEval200, errors={400: ('DeleteEval400', DeleteEval400), 404: ('DeleteEval404', DeleteEval404), 429: ('DeleteEval429', DeleteEval429)})
_GET_EVAL_RUNS = _c.Operation("GET", url_params=('after', 'limit', 'order', 'status', ), success=GetEvalRuns200, errors={400: ('GetEvalRuns400', GetEvalRuns400), 404: ('GetEvalRuns404', GetEvalRuns404), 429: ('GetEvalRuns429', GetEvalRuns429)})
_CREATE_EVAL_RUN = _c.Operation("POST", success=CreateEvalRun201, errors={400: ('CreateEvalRun400', CreateEvalRun400), 404: ('CreateEvalRun404', CreateEvalRun404), 429: ('CreateEvalRun429', CreateEvalRun429), 500: ('CreateEvalRun500', CreateEvalRun500)})
_GET_EVAL_RUN = _c.Operation("GET", success=GetEvalRun200, errors={400: ('GetEvalRun400', GetEvalRun400), 404: ('GetEvalRun404', GetEvalRun404), 429: ('GetEvalRun429', GetEvalRun429)})
_DELETE_EVAL_RUN = _c.Operation("DELETE", success=DeleteEvalRun200, errors={400: ('DeleteEvalRun400', DeleteEvalRun400), 404: ('DeleteEvalRun404', DeleteEvalRun404), 429: ('DeleteEvalRun429', DeleteEvalRun429)})
_CANCEL_EVAL_RUN = _c.Operation("POST", success=CancelEvalRun200, errors={429: ('CancelEvalRun429', CancelEvalRun429)})
_GET_EVAL_RUN_OUTPUT_ITEMS = _c.Operation("GET", url_params=('after', 'limit', 'status', 'order', ), success=GetEvalRunOutputItems200, errors={400: ('GetEvalRunOutputItems400', GetEvalRunOutputItems400), 404: ('GetEvalRunOutputItems404', GetEvalRunOutputItems404), 429: ('GetEvalRunOutputItems429', GetEvalRunOutputItems429)})
_GET_EVAL_RUN_OUTPUT_ITEM = _c.Operation("GET", success=GetEvalRunOutputItem200, errors={400: ('GetEvalRunOutputItem400', GetEvalRunOutputItem400), 404: ('GetEvalRunOutputItem404', GetEvalRunOutputItem404), 429: ('GetEvalRunOutputItem429', GetEvalRunOutputItem429)})
_LIST_FILES = _c.Operation("GET", url_params=('purpose', 'limit', 'order', 'after', ), success=ListFiles200, errors={400: ('ListFiles400', ListFiles400), 404: ('ListFiles404', ListFiles404), 429: ('ListFiles429', ListFiles429)})
_CREATE_FILE = _c.Operation("POST", success=CreateFile200, errors={400: ('CreateFile400', CreateFile400), 429: ('CreateFile429', CreateFile429), 500: ('CreateFile500', CreateFile500)})
_RETRIEVE_FILE = _c.Operation("GET", success=RetrieveFile200, errors={404: ('RetrieveFile404', RetrieveFile404), 429: ('RetrieveFile429', RetrieveFile429)})
_DELETE_FILE = _c.Operation("DELETE", success=DeleteFile200, errors={404: ('DeleteFile404', DeleteFile404), 429: ('DeleteFile429', DeleteFile429)})
_DOWNLOAD_FILE = _c.Operation("GET", binary_success=True, errors={400: ('DownloadFile400', DownloadFile400), 404: ('DownloadFile404', DownloadFile404), 429: ('DownloadFile429', DownloadFile429), 500: ('DownloadFile500', DownloadFile500)})
_DOWNLOAD_FILE_STREAM = _c.Operation("GET")
_RUN_GRADER = _c.Operation("POST", success=RunGrader200, errors={400: ('RunGrader400', RunGrader400), 429: ('RunGrader429', RunGrader429)})
_VALIDATE_GRADER = _c.Operation("POST", success=ValidateGrader200, errors={400: ('ValidateGrader400', ValidateGrader400), 429: ('ValidateGrader429', ValidateGrader429)})
_LIST_FINE_TUNING_CHECKPOINT_PERMISSIONS = _c.Operation("GET", url_params=('project_id', 'after', 'limit', 'order', ), success=ListFineTuningCheckpointPermissions200, errors={400: ('ListFineTuningCheckpointPermissions400', ListFineTuningCheckpointPermissions400), 429: ('ListFineTuningCheckpointPermissions429', ListFineTuningCheckpointPermissions429)})
_CREATE_FINE_TUNING_CHECKPOINT_PERMISSION = _c.Operation("POST", success=CreateFineTuningCheckpointPermission200, errors={400: ('CreateFineTuningCheckpointPermission400', CreateFineTuningCheckpointPermission400), 404: ('CreateFineTuningCheckpointPermission404', CreateFineTuningCheckpointPermission404), 429: ('CreateFineTuningCheckpointPermission429', CreateFineTuningCheckpointPermission429)})
_DELETE_FINE_TUNING_CHECKPOINT_PERMISSION = _c.Operation("DELETE", success=DeleteFineTuningCheckpointPermission200, errors={400: ('DeleteFineTuningCheckpointPermission400', DeleteFineTuningCheckpointPermission400), 404: ('DeleteFineTuningCheckpointPermission404', DeleteFineTuningCheckpointPermission404), 429: ('DeleteFineTuningCheckpointPermission429', DeleteFineTuningCheckpointPermission429)})
_LIST_PAGINATED_FINE_TUNING_JOBS = _c.Operation("GET", url_params=('after', 'limit', 'metadata', ), success=ListPaginatedFineTuningJobs200, errors={400: ('ListPaginatedFineTuningJobs400', ListPaginatedFineTuningJobs400), 429: ('ListPaginatedFineTuningJobs429', ListPaginatedFineTuningJobs429)})
_CREATE_FINE_TUNING_JOB = _c.Operation("POST", success=CreateFineTuningJob200, errors={400: ('CreateFineTuningJob400', CreateFineTuningJob400), 429: ('CreateFineTuningJob429', CreateFineTuningJob429)})
_RETRIEVE_FINE_TUNING_JOB = _c.Operation("GET", success=RetrieveFineTuningJob200, errors={404: ('RetrieveFineTuningJob404', RetrieveFineTuningJob404), 429: ('RetrieveFineTuningJob429', RetrieveFineTuningJob429)})
_CANCEL_FINE_TUNING_JOB = _c.Operation("POST", success=CancelFineTuningJob200, errors={400: ('CancelFineTuningJob400', CancelFineTuningJob400), 404: ('CancelFineTuningJob404', CancelFineTuningJob404), 429: ('CancelFineTuningJob429', CancelFineTuningJob429)})
_LIST_FINE_TUNING_JOB_CHECKPOINTS = _c.Operation("GET", url_params=('after', 'limit', ), success=ListFineTuningJobCheckpoints200, errors={400: ('ListFineTuningJobCheckpoints400', ListFineTuningJobCheckpoints400), 404: ('ListFineTuningJobCheckpoints404', ListFineTuningJobCheckpoints404), 429: ('ListFineTuningJobCheckpoints429', ListFineTuningJobCheckpoints429)})
_LIST_FINE_TUNING_EVENTS = _c.Operation("GET", url_params=('after', 'limit', ), success=ListFineTuningEvents200, errors={400: ('ListFineTuningEvents400', ListFineTuningEvents400), 404: ('ListFineTuningEvents404', ListFineTuningEvents404), 429: ('ListFineTuningEvents429', ListFineTuningEvents429)})
_PAUSE_FINE_TUNING_JOB = _c.Operation("POST", success=PauseFineTuningJob200, errors={400: ('PauseFineTuningJob400', PauseFineTuningJob400), 404: ('PauseFineTuningJob404', PauseFineTuningJob404), 429: ('PauseFineTuningJob429', PauseFineTuningJob429)})
_RESUME_FINE_TUNING_JOB = _c.Operation("POST", success=ResumeFineTuningJob200, errors={400: ('ResumeFineTuningJob400', ResumeFineTuningJob400), 404: ('ResumeFineTuningJob404', ResumeFineTuningJob404), 429: ('ResumeFineTuningJob429', ResumeFineTuningJob429)})
_CREATE_IMAGE_EDIT = _c.Operation("POST", success=CreateImageEdit200, errors={400: ('CreateImageEdit400', CreateImageEdit400), 403: ('CreateImageEdit403', CreateImageEdit403), 410: ('CreateImageEdit410', CreateImageEdit410), 429: ('CreateImageEdit429', CreateImageEdit429), 500: ('CreateImageEdit500', CreateImageEdit500), 503: ('CreateImageEdit503', CreateImageEdit503)})
_CREATE_IMAGE_EDIT_SSE = _c.Operation("POST")
_CREATE_IMAGE = _c.Operation("POST", success=CreateImage200, errors={400: ('CreateImage400', CreateImage400), 403: ('CreateImage403', CreateImage403), 410: ('CreateImage410', CreateImage410), 429: ('CreateImage429', CreateImage429), 500: ('CreateImage500', CreateImage500), 503: ('CreateImage503', CreateImage503)})
_CREATE_IMAGE_SSE = _c.Operation("POST")
_CREATE_IMAGE_VARIATION = _c.Operation("POST", success=CreateImageVariation200, errors={400: ('CreateImageVariation400', CreateImageVariation400), 403: ('CreateImageVariation403', CreateImageVariation403), 410: ('CreateImageVariation410', CreateImageVariation410), 429: ('CreateImageVariation429', CreateImageVariation429), 500: ('CreateImageVariation500', CreateImageVariation500)})
_CREATE_LIVE = _c.Operation("POST", success=CreateLive201, errors={400: ('CreateLive400', CreateLive400), 413: ('CreateLive413', CreateLive413), 429: ('CreateLive429', CreateLive429), 503: ('CreateLive503', CreateLive503), 504: ('CreateLive504', CreateLive504)})
_ACCEPT_LIVE_SESSION = _c.Operation("POST", void=(200, ), errors={400: ('AcceptLiveSession400', AcceptLiveSession400), 404: ('AcceptLiveSession404', AcceptLiveSession404), 409: ('AcceptLiveSession409', AcceptLiveSession409), 429: ('AcceptLiveSession429', AcceptLiveSession429), 503: ('AcceptLiveSession503', AcceptLiveSession503)})
_FORK_LIVE_SESSION = _c.Operation("POST", success=ForkLiveSession201, errors={400: ('ForkLiveSession400', ForkLiveSession400), 413: ('ForkLiveSession413', ForkLiveSession413), 429: ('ForkLiveSession429', ForkLiveSession429), 503: ('ForkLiveSession503', ForkLiveSession503)})
_HANGUP_LIVE_SESSION = _c.Operation("POST", void=(200, ), errors={404: ('HangupLiveSession404', HangupLiveSession404)})
_REFER_LIVE_SESSION = _c.Operation("POST", void=(200, ), errors={400: ('ReferLiveSession400', ReferLiveSession400), 404: ('ReferLiveSession404', ReferLiveSession404)})
_REJECT_LIVE_SESSION = _c.Operation("POST", void=(200, ), errors={400: ('RejectLiveSession400', RejectLiveSession400), 404: ('RejectLiveSession404', RejectLiveSession404), 409: ('RejectLiveSession409', RejectLiveSession409)})
_LIST_MODELS = _c.Operation("GET", success=ListModels200, errors={403: ('ListModels403', ListModels403)})
_RETRIEVE_MODEL = _c.Operation("GET", success=RetrieveModel200, errors={403: ('RetrieveModel403', RetrieveModel403), 404: ('RetrieveModel404', RetrieveModel404)})
_DELETE_MODEL = _c.Operation("DELETE", success=DeleteModel200, errors={403: ('DeleteModel403', DeleteModel403), 404: ('DeleteModel404', DeleteModel404)})
_CREATE_MODERATION = _c.Operation("POST", success=CreateModeration200, errors={400: ('CreateModeration400', CreateModeration400), 403: ('CreateModeration403', CreateModeration403), 429: ('CreateModeration429', CreateModeration429), 500: ('CreateModeration500', CreateModeration500), 503: ('CreateModeration503', CreateModeration503)})
_ADMIN_API_KEYS_LIST = _c.Operation("GET", url_params=('after', 'order', 'limit', ), success=AdminApiKeysList200, errors={400: ('AdminApiKeysList400', AdminApiKeysList400), 403: ('AdminApiKeysList403', AdminApiKeysList403)})
_ADMIN_API_KEYS_CREATE = _c.Operation("POST", success=AdminApiKeysCreate200, errors={400: ('AdminApiKeysCreate400', AdminApiKeysCreate400), 403: ('AdminApiKeysCreate403', AdminApiKeysCreate403), 404: ('AdminApiKeysCreate404', AdminApiKeysCreate404)})
_ADMIN_API_KEYS_GET = _c.Operation("GET", success=AdminApiKeysGet200, errors={403: ('AdminApiKeysGet403', AdminApiKeysGet403), 404: ('AdminApiKeysGet404', AdminApiKeysGet404)})
_ADMIN_API_KEYS_DELETE = _c.Operation("DELETE", success=AdminApiKeysDelete200, errors={403: ('AdminApiKeysDelete403', AdminApiKeysDelete403), 404: ('AdminApiKeysDelete404', AdminApiKeysDelete404)})
_LIST_AUDIT_LOGS = _c.Operation("GET", url_params=('effective_at[gt]', 'effective_at[gte]', 'effective_at[lt]', 'effective_at[lte]', 'project_ids[]', 'event_types[]', 'actor_ids[]', 'actor_emails[]', 'resource_ids[]', 'tenant_only', 'limit', 'after', 'before', ), success=ListAuditLogs200, errors={400: ('ListAuditLogs400', ListAuditLogs400), 404: ('ListAuditLogs404', ListAuditLogs404), 429: ('ListAuditLogs429', ListAuditLogs429)})
_LIST_ORGANIZATION_CERTIFICATES = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListOrganizationCertificates200, errors={400: ('ListOrganizationCertificates400', ListOrganizationCertificates400), 403: ('ListOrganizationCertificates403', ListOrganizationCertificates403), 429: ('ListOrganizationCertificates429', ListOrganizationCertificates429)})
_UPLOAD_CERTIFICATE = _c.Operation("POST", success=UploadCertificate200, errors={400: ('UploadCertificate400', UploadCertificate400), 403: ('UploadCertificate403', UploadCertificate403), 429: ('UploadCertificate429', UploadCertificate429)})
_ACTIVATE_ORGANIZATION_CERTIFICATES = _c.Operation("POST", success=ActivateOrganizationCertificates200, errors={400: ('ActivateOrganizationCertificates400', ActivateOrganizationCertificates400), 403: ('ActivateOrganizationCertificates403', ActivateOrganizationCertificates403), 404: ('ActivateOrganizationCertificates404', ActivateOrganizationCertificates404), 429: ('ActivateOrganizationCertificates429', ActivateOrganizationCertificates429), 500: ('ActivateOrganizationCertificates500', ActivateOrganizationCertificates500)})
_DEACTIVATE_ORGANIZATION_CERTIFICATES = _c.Operation("POST", success=DeactivateOrganizationCertificates200, errors={400: ('DeactivateOrganizationCertificates400', DeactivateOrganizationCertificates400), 403: ('DeactivateOrganizationCertificates403', DeactivateOrganizationCertificates403), 404: ('DeactivateOrganizationCertificates404', DeactivateOrganizationCertificates404), 429: ('DeactivateOrganizationCertificates429', DeactivateOrganizationCertificates429), 500: ('DeactivateOrganizationCertificates500', DeactivateOrganizationCertificates500)})
_GET_CERTIFICATE = _c.Operation("GET", url_params=('include', ), success=GetCertificate200, errors={400: ('GetCertificate400', GetCertificate400), 403: ('GetCertificate403', GetCertificate403), 404: ('GetCertificate404', GetCertificate404), 429: ('GetCertificate429', GetCertificate429)})
_MODIFY_CERTIFICATE = _c.Operation("POST", success=ModifyCertificate200, errors={400: ('ModifyCertificate400', ModifyCertificate400), 403: ('ModifyCertificate403', ModifyCertificate403), 404: ('ModifyCertificate404', ModifyCertificate404), 429: ('ModifyCertificate429', ModifyCertificate429), 500: ('ModifyCertificate500', ModifyCertificate500)})
_DELETE_CERTIFICATE = _c.Operation("DELETE", success=DeleteCertificate200, errors={400: ('DeleteCertificate400', DeleteCertificate400), 403: ('DeleteCertificate403', DeleteCertificate403), 404: ('DeleteCertificate404', DeleteCertificate404), 429: ('DeleteCertificate429', DeleteCertificate429)})
_USAGE_COSTS = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'project_ids', 'api_key_ids', 'line_items', 'group_by', 'limit', 'page', ), success=UsageCosts200, errors={400: ('UsageCosts400', UsageCosts400), 403: ('UsageCosts403', UsageCosts403), 429: ('UsageCosts429', UsageCosts429)})
_RETRIEVE_ORGANIZATION_DATA_RETENTION = _c.Operation("GET", success=RetrieveOrganizationDataRetention200, errors={403: ('RetrieveOrganizationDataRetention403', RetrieveOrganizationDataRetention403), 404: ('RetrieveOrganizationDataRetention404', RetrieveOrganizationDataRetention404)})
_UPDATE_ORGANIZATION_DATA_RETENTION = _c.Operation("POST", success=UpdateOrganizationDataRetention200, errors={400: ('UpdateOrganizationDataRetention400', UpdateOrganizationDataRetention400), 403: ('UpdateOrganizationDataRetention403', UpdateOrganizationDataRetention403), 404: ('UpdateOrganizationDataRetention404', UpdateOrganizationDataRetention404)})
_LIST_GROUPS = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListGroups200, errors={400: ('ListGroups400', ListGroups400), 403: ('ListGroups403', ListGroups403), 404: ('ListGroups404', ListGroups404), 429: ('ListGroups429', ListGroups429)})
_CREATE_GROUP = _c.Operation("POST", success=CreateGroup200, errors={400: ('CreateGroup400', CreateGroup400), 403: ('CreateGroup403', CreateGroup403), 404: ('CreateGroup404', CreateGroup404), 422: ('CreateGroup422', CreateGroup422), 429: ('CreateGroup429', CreateGroup429), 500: ('CreateGroup500', CreateGroup500)})
_RETRIEVE_GROUP = _c.Operation("GET", success=RetrieveGroup200, errors={400: ('RetrieveGroup400', RetrieveGroup400), 403: ('RetrieveGroup403', RetrieveGroup403), 404: ('RetrieveGroup404', RetrieveGroup404), 429: ('RetrieveGroup429', RetrieveGroup429), 500: ('RetrieveGroup500', RetrieveGroup500)})
_UPDATE_GROUP = _c.Operation("POST", success=UpdateGroup200, errors={400: ('UpdateGroup400', UpdateGroup400), 403: ('UpdateGroup403', UpdateGroup403), 404: ('UpdateGroup404', UpdateGroup404), 429: ('UpdateGroup429', UpdateGroup429), 500: ('UpdateGroup500', UpdateGroup500)})
_DELETE_GROUP = _c.Operation("DELETE", success=DeleteGroup200, errors={400: ('DeleteGroup400', DeleteGroup400), 403: ('DeleteGroup403', DeleteGroup403), 404: ('DeleteGroup404', DeleteGroup404), 429: ('DeleteGroup429', DeleteGroup429)})
_LIST_GROUP_ROLE_ASSIGNMENTS = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListGroupRoleAssignments200, errors={400: ('ListGroupRoleAssignments400', ListGroupRoleAssignments400), 403: ('ListGroupRoleAssignments403', ListGroupRoleAssignments403), 404: ('ListGroupRoleAssignments404', ListGroupRoleAssignments404), 429: ('ListGroupRoleAssignments429', ListGroupRoleAssignments429)})
_ASSIGN_GROUP_ROLE = _c.Operation("POST", success=AssignGroupRole200, errors={400: ('AssignGroupRole400', AssignGroupRole400), 403: ('AssignGroupRole403', AssignGroupRole403), 404: ('AssignGroupRole404', AssignGroupRole404), 429: ('AssignGroupRole429', AssignGroupRole429)})
_RETRIEVE_GROUP_ROLE = _c.Operation("GET", success=RetrieveGroupRole200, errors={400: ('RetrieveGroupRole400', RetrieveGroupRole400), 403: ('RetrieveGroupRole403', RetrieveGroupRole403), 404: ('RetrieveGroupRole404', RetrieveGroupRole404), 429: ('RetrieveGroupRole429', RetrieveGroupRole429)})
_UNASSIGN_GROUP_ROLE = _c.Operation("DELETE", success=UnassignGroupRole200, errors={400: ('UnassignGroupRole400', UnassignGroupRole400), 403: ('UnassignGroupRole403', UnassignGroupRole403), 404: ('UnassignGroupRole404', UnassignGroupRole404), 429: ('UnassignGroupRole429', UnassignGroupRole429)})
_LIST_GROUP_USERS = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListGroupUsers200, errors={400: ('ListGroupUsers400', ListGroupUsers400), 403: ('ListGroupUsers403', ListGroupUsers403), 404: ('ListGroupUsers404', ListGroupUsers404), 429: ('ListGroupUsers429', ListGroupUsers429), 502: ('ListGroupUsers502', ListGroupUsers502)})
_ADD_GROUP_USER = _c.Operation("POST", success=AddGroupUser200, errors={400: ('AddGroupUser400', AddGroupUser400), 403: ('AddGroupUser403', AddGroupUser403), 404: ('AddGroupUser404', AddGroupUser404), 409: ('AddGroupUser409', AddGroupUser409), 429: ('AddGroupUser429', AddGroupUser429)})
_RETRIEVE_GROUP_USER = _c.Operation("GET", success=RetrieveGroupUser200, errors={400: ('RetrieveGroupUser400', RetrieveGroupUser400), 403: ('RetrieveGroupUser403', RetrieveGroupUser403), 404: ('RetrieveGroupUser404', RetrieveGroupUser404), 429: ('RetrieveGroupUser429', RetrieveGroupUser429)})
_REMOVE_GROUP_USER = _c.Operation("DELETE", success=RemoveGroupUser200, errors={400: ('RemoveGroupUser400', RemoveGroupUser400), 403: ('RemoveGroupUser403', RemoveGroupUser403), 404: ('RemoveGroupUser404', RemoveGroupUser404), 409: ('RemoveGroupUser409', RemoveGroupUser409), 429: ('RemoveGroupUser429', RemoveGroupUser429)})
_LIST_INVITES = _c.Operation("GET", url_params=('limit', 'after', ), success=ListInvites200, errors={400: ('ListInvites400', ListInvites400), 403: ('ListInvites403', ListInvites403), 404: ('ListInvites404', ListInvites404), 429: ('ListInvites429', ListInvites429)})
_INVITE_USER = _c.Operation("POST", status_success={200: InviteUser200, 201: InviteUser201}, errors={400: ('InviteUser400', InviteUser400), 403: ('InviteUser403', InviteUser403), 429: ('InviteUser429', InviteUser429)})
_RETRIEVE_INVITE = _c.Operation("GET", success=RetrieveInvite200, errors={400: ('RetrieveInvite400', RetrieveInvite400), 403: ('RetrieveInvite403', RetrieveInvite403), 404: ('RetrieveInvite404', RetrieveInvite404), 429: ('RetrieveInvite429', RetrieveInvite429), 500: ('RetrieveInvite500', RetrieveInvite500)})
_DELETE_INVITE = _c.Operation("DELETE", success=DeleteInvite200, errors={400: ('DeleteInvite400', DeleteInvite400), 403: ('DeleteInvite403', DeleteInvite403), 404: ('DeleteInvite404', DeleteInvite404), 429: ('DeleteInvite429', DeleteInvite429)})
_LIST_PROJECTS = _c.Operation("GET", url_params=('limit', 'after', 'include_archived', ), success=ListProjects200, errors={400: ('ListProjects400', ListProjects400), 403: ('ListProjects403', ListProjects403), 404: ('ListProjects404', ListProjects404), 429: ('ListProjects429', ListProjects429)})
_CREATE_PROJECT = _c.Operation("POST", status_success={200: CreateProject200, 201: CreateProject201}, errors={400: ('CreateProject400', CreateProject400), 403: ('CreateProject403', CreateProject403), 429: ('CreateProject429', CreateProject429)})
_RETRIEVE_PROJECT = _c.Operation("GET", success=RetrieveProject200, errors={403: ('RetrieveProject403', RetrieveProject403), 404: ('RetrieveProject404', RetrieveProject404), 429: ('RetrieveProject429', RetrieveProject429)})
_MODIFY_PROJECT = _c.Operation("POST", success=ModifyProject200, errors={400: ('ModifyProject400', ModifyProject400), 403: ('ModifyProject403', ModifyProject403), 404: ('ModifyProject404', ModifyProject404), 429: ('ModifyProject429', ModifyProject429)})
_LIST_PROJECT_API_KEYS = _c.Operation("GET", url_params=('limit', 'after', 'owner_project_access', ), success=ListProjectApiKeys200, errors={400: ('ListProjectApiKeys400', ListProjectApiKeys400), 403: ('ListProjectApiKeys403', ListProjectApiKeys403), 404: ('ListProjectApiKeys404', ListProjectApiKeys404), 429: ('ListProjectApiKeys429', ListProjectApiKeys429)})
_RETRIEVE_PROJECT_API_KEY = _c.Operation("GET", success=RetrieveProjectApiKey200, errors={400: ('RetrieveProjectApiKey400', RetrieveProjectApiKey400), 403: ('RetrieveProjectApiKey403', RetrieveProjectApiKey403), 404: ('RetrieveProjectApiKey404', RetrieveProjectApiKey404), 429: ('RetrieveProjectApiKey429', RetrieveProjectApiKey429)})
_DELETE_PROJECT_API_KEY = _c.Operation("DELETE", success=DeleteProjectApiKey200, errors={400: ('DeleteProjectApiKey400', DeleteProjectApiKey400), 403: ('DeleteProjectApiKey403', DeleteProjectApiKey403), 404: ('DeleteProjectApiKey404', DeleteProjectApiKey404), 429: ('DeleteProjectApiKey429', DeleteProjectApiKey429)})
_ARCHIVE_PROJECT = _c.Operation("POST", success=ArchiveProject200, errors={400: ('ArchiveProject400', ArchiveProject400), 403: ('ArchiveProject403', ArchiveProject403), 404: ('ArchiveProject404', ArchiveProject404), 429: ('ArchiveProject429', ArchiveProject429)})
_LIST_PROJECT_CERTIFICATES = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListProjectCertificates200, errors={400: ('ListProjectCertificates400', ListProjectCertificates400), 403: ('ListProjectCertificates403', ListProjectCertificates403), 429: ('ListProjectCertificates429', ListProjectCertificates429)})
_ACTIVATE_PROJECT_CERTIFICATES = _c.Operation("POST", success=ActivateProjectCertificates200, errors={400: ('ActivateProjectCertificates400', ActivateProjectCertificates400), 403: ('ActivateProjectCertificates403', ActivateProjectCertificates403), 404: ('ActivateProjectCertificates404', ActivateProjectCertificates404), 429: ('ActivateProjectCertificates429', ActivateProjectCertificates429), 500: ('ActivateProjectCertificates500', ActivateProjectCertificates500)})
_DEACTIVATE_PROJECT_CERTIFICATES = _c.Operation("POST", success=DeactivateProjectCertificates200, errors={400: ('DeactivateProjectCertificates400', DeactivateProjectCertificates400), 403: ('DeactivateProjectCertificates403', DeactivateProjectCertificates403), 404: ('DeactivateProjectCertificates404', DeactivateProjectCertificates404), 429: ('DeactivateProjectCertificates429', DeactivateProjectCertificates429), 500: ('DeactivateProjectCertificates500', DeactivateProjectCertificates500)})
_RETRIEVE_PROJECT_DATA_RETENTION = _c.Operation("GET", success=RetrieveProjectDataRetention200, errors={400: ('RetrieveProjectDataRetention400', RetrieveProjectDataRetention400), 403: ('RetrieveProjectDataRetention403', RetrieveProjectDataRetention403), 404: ('RetrieveProjectDataRetention404', RetrieveProjectDataRetention404)})
_UPDATE_PROJECT_DATA_RETENTION = _c.Operation("POST", success=UpdateProjectDataRetention200, errors={400: ('UpdateProjectDataRetention400', UpdateProjectDataRetention400), 403: ('UpdateProjectDataRetention403', UpdateProjectDataRetention403), 404: ('UpdateProjectDataRetention404', UpdateProjectDataRetention404)})
_LIST_PROJECT_GROUPS = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListProjectGroups200, errors={400: ('ListProjectGroups400', ListProjectGroups400), 403: ('ListProjectGroups403', ListProjectGroups403), 404: ('ListProjectGroups404', ListProjectGroups404), 429: ('ListProjectGroups429', ListProjectGroups429)})
_ADD_PROJECT_GROUP = _c.Operation("POST", success=AddProjectGroup200, errors={400: ('AddProjectGroup400', AddProjectGroup400), 403: ('AddProjectGroup403', AddProjectGroup403), 404: ('AddProjectGroup404', AddProjectGroup404), 429: ('AddProjectGroup429', AddProjectGroup429), 500: ('AddProjectGroup500', AddProjectGroup500)})
_RETRIEVE_PROJECT_GROUP = _c.Operation("GET", url_params=('group_type', ), success=RetrieveProjectGroup200, errors={400: ('RetrieveProjectGroup400', RetrieveProjectGroup400), 403: ('RetrieveProjectGroup403', RetrieveProjectGroup403), 404: ('RetrieveProjectGroup404', RetrieveProjectGroup404), 429: ('RetrieveProjectGroup429', RetrieveProjectGroup429)})
_REMOVE_PROJECT_GROUP = _c.Operation("DELETE", success=RemoveProjectGroup200, errors={400: ('RemoveProjectGroup400', RemoveProjectGroup400), 403: ('RemoveProjectGroup403', RemoveProjectGroup403), 404: ('RemoveProjectGroup404', RemoveProjectGroup404), 429: ('RemoveProjectGroup429', RemoveProjectGroup429)})
_RETRIEVE_PROJECT_HOSTED_TOOL_PERMISSIONS = _c.Operation("GET", success=RetrieveProjectHostedToolPermissions200, errors={400: ('RetrieveProjectHostedToolPermissions400', RetrieveProjectHostedToolPermissions400), 403: ('RetrieveProjectHostedToolPermissions403', RetrieveProjectHostedToolPermissions403), 404: ('RetrieveProjectHostedToolPermissions404', RetrieveProjectHostedToolPermissions404), 429: ('RetrieveProjectHostedToolPermissions429', RetrieveProjectHostedToolPermissions429)})
_UPDATE_PROJECT_HOSTED_TOOL_PERMISSIONS = _c.Operation("POST", success=UpdateProjectHostedToolPermissions200, errors={400: ('UpdateProjectHostedToolPermissions400', UpdateProjectHostedToolPermissions400), 403: ('UpdateProjectHostedToolPermissions403', UpdateProjectHostedToolPermissions403), 404: ('UpdateProjectHostedToolPermissions404', UpdateProjectHostedToolPermissions404), 409: ('UpdateProjectHostedToolPermissions409', UpdateProjectHostedToolPermissions409), 429: ('UpdateProjectHostedToolPermissions429', UpdateProjectHostedToolPermissions429)})
_RETRIEVE_PROJECT_MODEL_PERMISSIONS = _c.Operation("GET", success=RetrieveProjectModelPermissions200, errors={400: ('RetrieveProjectModelPermissions400', RetrieveProjectModelPermissions400), 403: ('RetrieveProjectModelPermissions403', RetrieveProjectModelPermissions403), 404: ('RetrieveProjectModelPermissions404', RetrieveProjectModelPermissions404), 429: ('RetrieveProjectModelPermissions429', RetrieveProjectModelPermissions429)})
_UPDATE_PROJECT_MODEL_PERMISSIONS = _c.Operation("POST", success=UpdateProjectModelPermissions200, errors={400: ('UpdateProjectModelPermissions400', UpdateProjectModelPermissions400), 403: ('UpdateProjectModelPermissions403', UpdateProjectModelPermissions403), 404: ('UpdateProjectModelPermissions404', UpdateProjectModelPermissions404), 429: ('UpdateProjectModelPermissions429', UpdateProjectModelPermissions429)})
_DELETE_PROJECT_MODEL_PERMISSIONS = _c.Operation("DELETE", success=DeleteProjectModelPermissions200, errors={400: ('DeleteProjectModelPermissions400', DeleteProjectModelPermissions400), 403: ('DeleteProjectModelPermissions403', DeleteProjectModelPermissions403), 404: ('DeleteProjectModelPermissions404', DeleteProjectModelPermissions404), 429: ('DeleteProjectModelPermissions429', DeleteProjectModelPermissions429)})
_LIST_PROJECT_RATE_LIMITS = _c.Operation("GET", url_params=('limit', 'after', 'before', ), success=ListProjectRateLimits200, errors={400: ('ListProjectRateLimits400', ListProjectRateLimits400), 403: ('ListProjectRateLimits403', ListProjectRateLimits403), 404: ('ListProjectRateLimits404', ListProjectRateLimits404)})
_UPDATE_PROJECT_RATE_LIMITS = _c.Operation("POST", success=UpdateProjectRateLimits200, errors={400: ('UpdateProjectRateLimits400', UpdateProjectRateLimits400), 403: ('UpdateProjectRateLimits403', UpdateProjectRateLimits403), 404: ('UpdateProjectRateLimits404', UpdateProjectRateLimits404)})
_LIST_PROJECT_SERVICE_ACCOUNTS = _c.Operation("GET", url_params=('limit', 'after', ), success=ListProjectServiceAccounts200, errors={400: ('ListProjectServiceAccounts400', ListProjectServiceAccounts400), 403: ('ListProjectServiceAccounts403', ListProjectServiceAccounts403), 404: ('ListProjectServiceAccounts404', ListProjectServiceAccounts404), 429: ('ListProjectServiceAccounts429', ListProjectServiceAccounts429)})
_CREATE_PROJECT_SERVICE_ACCOUNT = _c.Operation("POST", status_success={200: CreateProjectServiceAccount200, 201: CreateProjectServiceAccount201}, errors={400: ('CreateProjectServiceAccount400', CreateProjectServiceAccount400), 403: ('CreateProjectServiceAccount403', CreateProjectServiceAccount403), 404: ('CreateProjectServiceAccount404', CreateProjectServiceAccount404), 429: ('CreateProjectServiceAccount429', CreateProjectServiceAccount429)})
_RETRIEVE_PROJECT_SERVICE_ACCOUNT = _c.Operation("GET", success=RetrieveProjectServiceAccount200, errors={400: ('RetrieveProjectServiceAccount400', RetrieveProjectServiceAccount400), 403: ('RetrieveProjectServiceAccount403', RetrieveProjectServiceAccount403), 404: ('RetrieveProjectServiceAccount404', RetrieveProjectServiceAccount404), 429: ('RetrieveProjectServiceAccount429', RetrieveProjectServiceAccount429)})
_UPDATE_PROJECT_SERVICE_ACCOUNT = _c.Operation("POST", success=UpdateProjectServiceAccount200, errors={400: ('UpdateProjectServiceAccount400', UpdateProjectServiceAccount400), 403: ('UpdateProjectServiceAccount403', UpdateProjectServiceAccount403), 404: ('UpdateProjectServiceAccount404', UpdateProjectServiceAccount404), 429: ('UpdateProjectServiceAccount429', UpdateProjectServiceAccount429)})
_DELETE_PROJECT_SERVICE_ACCOUNT = _c.Operation("DELETE", success=DeleteProjectServiceAccount200, errors={400: ('DeleteProjectServiceAccount400', DeleteProjectServiceAccount400), 403: ('DeleteProjectServiceAccount403', DeleteProjectServiceAccount403), 404: ('DeleteProjectServiceAccount404', DeleteProjectServiceAccount404), 429: ('DeleteProjectServiceAccount429', DeleteProjectServiceAccount429)})
_LIST_PROJECT_SPEND_ALERTS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', ), success=ListProjectSpendAlerts200, errors={400: ('ListProjectSpendAlerts400', ListProjectSpendAlerts400), 403: ('ListProjectSpendAlerts403', ListProjectSpendAlerts403), 404: ('ListProjectSpendAlerts404', ListProjectSpendAlerts404)})
_CREATE_PROJECT_SPEND_ALERT = _c.Operation("POST", success=CreateProjectSpendAlert200, errors={400: ('CreateProjectSpendAlert400', CreateProjectSpendAlert400), 403: ('CreateProjectSpendAlert403', CreateProjectSpendAlert403), 404: ('CreateProjectSpendAlert404', CreateProjectSpendAlert404)})
_RETRIEVE_PROJECT_SPEND_ALERT = _c.Operation("GET", success=RetrieveProjectSpendAlert200, errors={400: ('RetrieveProjectSpendAlert400', RetrieveProjectSpendAlert400), 403: ('RetrieveProjectSpendAlert403', RetrieveProjectSpendAlert403), 404: ('RetrieveProjectSpendAlert404', RetrieveProjectSpendAlert404)})
_UPDATE_PROJECT_SPEND_ALERT = _c.Operation("POST", success=UpdateProjectSpendAlert200, errors={400: ('UpdateProjectSpendAlert400', UpdateProjectSpendAlert400), 403: ('UpdateProjectSpendAlert403', UpdateProjectSpendAlert403), 404: ('UpdateProjectSpendAlert404', UpdateProjectSpendAlert404)})
_DELETE_PROJECT_SPEND_ALERT = _c.Operation("DELETE", success=DeleteProjectSpendAlert200, errors={400: ('DeleteProjectSpendAlert400', DeleteProjectSpendAlert400), 403: ('DeleteProjectSpendAlert403', DeleteProjectSpendAlert403), 404: ('DeleteProjectSpendAlert404', DeleteProjectSpendAlert404)})
_LIST_PROJECT_USERS = _c.Operation("GET", url_params=('limit', 'after', ), success=ListProjectUsers200, errors={400: ('ListProjectUsers400', ListProjectUsers400), 403: ('ListProjectUsers403', ListProjectUsers403), 404: ('ListProjectUsers404', ListProjectUsers404), 429: ('ListProjectUsers429', ListProjectUsers429)})
_CREATE_PROJECT_USER = _c.Operation("POST", status_success={200: CreateProjectUser200, 201: CreateProjectUser201}, errors={400: ('CreateProjectUser400', CreateProjectUser400), 403: ('CreateProjectUser403', CreateProjectUser403), 404: ('CreateProjectUser404', CreateProjectUser404), 409: ('CreateProjectUser409', CreateProjectUser409), 429: ('CreateProjectUser429', CreateProjectUser429)})
_RETRIEVE_PROJECT_USER = _c.Operation("GET", success=RetrieveProjectUser200, errors={400: ('RetrieveProjectUser400', RetrieveProjectUser400), 403: ('RetrieveProjectUser403', RetrieveProjectUser403), 404: ('RetrieveProjectUser404', RetrieveProjectUser404), 429: ('RetrieveProjectUser429', RetrieveProjectUser429)})
_MODIFY_PROJECT_USER = _c.Operation("POST", success=ModifyProjectUser200, errors={400: ('ModifyProjectUser400', ModifyProjectUser400), 403: ('ModifyProjectUser403', ModifyProjectUser403), 404: ('ModifyProjectUser404', ModifyProjectUser404), 429: ('ModifyProjectUser429', ModifyProjectUser429)})
_DELETE_PROJECT_USER = _c.Operation("DELETE", success=DeleteProjectUser200, errors={400: ('DeleteProjectUser400', DeleteProjectUser400), 403: ('DeleteProjectUser403', DeleteProjectUser403), 404: ('DeleteProjectUser404', DeleteProjectUser404), 429: ('DeleteProjectUser429', DeleteProjectUser429)})
_LIST_ROLES = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListRoles200, errors={400: ('ListRoles400', ListRoles400), 403: ('ListRoles403', ListRoles403), 404: ('ListRoles404', ListRoles404), 429: ('ListRoles429', ListRoles429)})
_CREATE_ROLE = _c.Operation("POST", success=CreateRole200, errors={400: ('CreateRole400', CreateRole400), 403: ('CreateRole403', CreateRole403), 404: ('CreateRole404', CreateRole404), 429: ('CreateRole429', CreateRole429)})
_RETRIEVE_ROLE = _c.Operation("GET", success=RetrieveRole200, errors={403: ('RetrieveRole403', RetrieveRole403), 404: ('RetrieveRole404', RetrieveRole404), 429: ('RetrieveRole429', RetrieveRole429)})
_UPDATE_ROLE = _c.Operation("POST", success=UpdateRole200, errors={400: ('UpdateRole400', UpdateRole400), 403: ('UpdateRole403', UpdateRole403), 404: ('UpdateRole404', UpdateRole404), 429: ('UpdateRole429', UpdateRole429)})
_DELETE_ROLE = _c.Operation("DELETE", success=DeleteRole200, errors={400: ('DeleteRole400', DeleteRole400), 403: ('DeleteRole403', DeleteRole403), 404: ('DeleteRole404', DeleteRole404), 429: ('DeleteRole429', DeleteRole429)})
_LIST_ORGANIZATION_SPEND_ALERTS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', ), success=ListOrganizationSpendAlerts200, errors={400: ('ListOrganizationSpendAlerts400', ListOrganizationSpendAlerts400), 403: ('ListOrganizationSpendAlerts403', ListOrganizationSpendAlerts403), 404: ('ListOrganizationSpendAlerts404', ListOrganizationSpendAlerts404)})
_CREATE_ORGANIZATION_SPEND_ALERT = _c.Operation("POST", success=CreateOrganizationSpendAlert200, errors={400: ('CreateOrganizationSpendAlert400', CreateOrganizationSpendAlert400), 403: ('CreateOrganizationSpendAlert403', CreateOrganizationSpendAlert403)})
_RETRIEVE_ORGANIZATION_SPEND_ALERT = _c.Operation("GET", success=RetrieveOrganizationSpendAlert200, errors={403: ('RetrieveOrganizationSpendAlert403', RetrieveOrganizationSpendAlert403), 404: ('RetrieveOrganizationSpendAlert404', RetrieveOrganizationSpendAlert404)})
_UPDATE_ORGANIZATION_SPEND_ALERT = _c.Operation("POST", success=UpdateOrganizationSpendAlert200, errors={400: ('UpdateOrganizationSpendAlert400', UpdateOrganizationSpendAlert400), 403: ('UpdateOrganizationSpendAlert403', UpdateOrganizationSpendAlert403), 404: ('UpdateOrganizationSpendAlert404', UpdateOrganizationSpendAlert404)})
_DELETE_ORGANIZATION_SPEND_ALERT = _c.Operation("DELETE", success=DeleteOrganizationSpendAlert200, errors={403: ('DeleteOrganizationSpendAlert403', DeleteOrganizationSpendAlert403), 404: ('DeleteOrganizationSpendAlert404', DeleteOrganizationSpendAlert404)})
_USAGE_AUDIO_SPEECHES = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'project_ids', 'user_ids', 'api_key_ids', 'models', 'group_by', 'limit', 'page', ), success=UsageAudioSpeeches200, errors={400: ('UsageAudioSpeeches400', UsageAudioSpeeches400), 403: ('UsageAudioSpeeches403', UsageAudioSpeeches403), 429: ('UsageAudioSpeeches429', UsageAudioSpeeches429)})
_USAGE_AUDIO_TRANSCRIPTIONS = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'project_ids', 'user_ids', 'api_key_ids', 'models', 'group_by', 'limit', 'page', ), success=UsageAudioTranscriptions200, errors={400: ('UsageAudioTranscriptions400', UsageAudioTranscriptions400), 403: ('UsageAudioTranscriptions403', UsageAudioTranscriptions403), 429: ('UsageAudioTranscriptions429', UsageAudioTranscriptions429)})
_USAGE_CODE_INTERPRETER_SESSIONS = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'project_ids', 'group_by', 'limit', 'page', ), success=UsageCodeInterpreterSessions200, errors={400: ('UsageCodeInterpreterSessions400', UsageCodeInterpreterSessions400), 403: ('UsageCodeInterpreterSessions403', UsageCodeInterpreterSessions403), 429: ('UsageCodeInterpreterSessions429', UsageCodeInterpreterSessions429)})
_USAGE_COMPLETIONS = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'project_ids', 'user_ids', 'api_key_ids', 'models', 'batch', 'group_by', 'limit', 'page', ), success=UsageCompletions200, errors={400: ('UsageCompletions400', UsageCompletions400), 403: ('UsageCompletions403', UsageCompletions403), 429: ('UsageCompletions429', UsageCompletions429)})
_USAGE_EMBEDDINGS = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'project_ids', 'user_ids', 'api_key_ids', 'models', 'group_by', 'limit', 'page', ), success=UsageEmbeddings200, errors={400: ('UsageEmbeddings400', UsageEmbeddings400), 403: ('UsageEmbeddings403', UsageEmbeddings403), 429: ('UsageEmbeddings429', UsageEmbeddings429)})
_USAGE_FILE_SEARCH_CALLS = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'project_ids', 'user_ids', 'api_key_ids', 'vector_store_ids', 'group_by', 'limit', 'page', ), success=UsageFileSearchCalls200, errors={400: ('UsageFileSearchCalls400', UsageFileSearchCalls400), 403: ('UsageFileSearchCalls403', UsageFileSearchCalls403), 429: ('UsageFileSearchCalls429', UsageFileSearchCalls429)})
_USAGE_IMAGES = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'sources', 'sizes', 'project_ids', 'user_ids', 'api_key_ids', 'models', 'group_by', 'limit', 'page', ), success=UsageImages200, errors={400: ('UsageImages400', UsageImages400), 403: ('UsageImages403', UsageImages403), 429: ('UsageImages429', UsageImages429)})
_USAGE_MODERATIONS = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'project_ids', 'user_ids', 'api_key_ids', 'models', 'group_by', 'limit', 'page', ), success=UsageModerations200, errors={400: ('UsageModerations400', UsageModerations400), 403: ('UsageModerations403', UsageModerations403), 429: ('UsageModerations429', UsageModerations429)})
_USAGE_VECTOR_STORES = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'project_ids', 'group_by', 'limit', 'page', ), success=UsageVectorStores200, errors={400: ('UsageVectorStores400', UsageVectorStores400), 403: ('UsageVectorStores403', UsageVectorStores403), 429: ('UsageVectorStores429', UsageVectorStores429)})
_USAGE_WEB_SEARCH_CALLS = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'project_ids', 'user_ids', 'api_key_ids', 'models', 'context_levels', 'group_by', 'limit', 'page', ), success=UsageWebSearchCalls200, errors={400: ('UsageWebSearchCalls400', UsageWebSearchCalls400), 403: ('UsageWebSearchCalls403', UsageWebSearchCalls403), 429: ('UsageWebSearchCalls429', UsageWebSearchCalls429)})
_LIST_USERS = _c.Operation("GET", url_params=('limit', 'after', 'emails', ), success=ListUsers200, errors={400: ('ListUsers400', ListUsers400), 403: ('ListUsers403', ListUsers403), 429: ('ListUsers429', ListUsers429)})
_RETRIEVE_USER = _c.Operation("GET", success=RetrieveUser200, errors={403: ('RetrieveUser403', RetrieveUser403), 404: ('RetrieveUser404', RetrieveUser404), 429: ('RetrieveUser429', RetrieveUser429)})
_MODIFY_USER = _c.Operation("POST", success=ModifyUser200, errors={400: ('ModifyUser400', ModifyUser400), 403: ('ModifyUser403', ModifyUser403), 404: ('ModifyUser404', ModifyUser404), 429: ('ModifyUser429', ModifyUser429)})
_DELETE_USER = _c.Operation("DELETE", success=DeleteUser200, errors={400: ('DeleteUser400', DeleteUser400), 403: ('DeleteUser403', DeleteUser403), 404: ('DeleteUser404', DeleteUser404), 429: ('DeleteUser429', DeleteUser429)})
_LIST_USER_ROLE_ASSIGNMENTS = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListUserRoleAssignments200, errors={400: ('ListUserRoleAssignments400', ListUserRoleAssignments400), 403: ('ListUserRoleAssignments403', ListUserRoleAssignments403), 404: ('ListUserRoleAssignments404', ListUserRoleAssignments404), 429: ('ListUserRoleAssignments429', ListUserRoleAssignments429)})
_ASSIGN_USER_ROLE = _c.Operation("POST", success=AssignUserRole200, errors={400: ('AssignUserRole400', AssignUserRole400), 403: ('AssignUserRole403', AssignUserRole403), 404: ('AssignUserRole404', AssignUserRole404), 429: ('AssignUserRole429', AssignUserRole429)})
_RETRIEVE_USER_ROLE = _c.Operation("GET", success=RetrieveUserRole200, errors={400: ('RetrieveUserRole400', RetrieveUserRole400), 403: ('RetrieveUserRole403', RetrieveUserRole403), 404: ('RetrieveUserRole404', RetrieveUserRole404), 429: ('RetrieveUserRole429', RetrieveUserRole429)})
_UNASSIGN_USER_ROLE = _c.Operation("DELETE", success=UnassignUserRole200, errors={400: ('UnassignUserRole400', UnassignUserRole400), 403: ('UnassignUserRole403', UnassignUserRole403), 404: ('UnassignUserRole404', UnassignUserRole404), 429: ('UnassignUserRole429', UnassignUserRole429)})
_LIST_PROJECT_GROUP_ROLE_ASSIGNMENTS = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListProjectGroupRoleAssignments200, errors={400: ('ListProjectGroupRoleAssignments400', ListProjectGroupRoleAssignments400), 403: ('ListProjectGroupRoleAssignments403', ListProjectGroupRoleAssignments403), 404: ('ListProjectGroupRoleAssignments404', ListProjectGroupRoleAssignments404), 429: ('ListProjectGroupRoleAssignments429', ListProjectGroupRoleAssignments429)})
_ASSIGN_PROJECT_GROUP_ROLE = _c.Operation("POST", success=AssignProjectGroupRole200, errors={400: ('AssignProjectGroupRole400', AssignProjectGroupRole400), 403: ('AssignProjectGroupRole403', AssignProjectGroupRole403), 404: ('AssignProjectGroupRole404', AssignProjectGroupRole404), 429: ('AssignProjectGroupRole429', AssignProjectGroupRole429)})
_RETRIEVE_PROJECT_GROUP_ROLE = _c.Operation("GET", success=RetrieveProjectGroupRole200, errors={400: ('RetrieveProjectGroupRole400', RetrieveProjectGroupRole400), 403: ('RetrieveProjectGroupRole403', RetrieveProjectGroupRole403), 404: ('RetrieveProjectGroupRole404', RetrieveProjectGroupRole404), 429: ('RetrieveProjectGroupRole429', RetrieveProjectGroupRole429)})
_UNASSIGN_PROJECT_GROUP_ROLE = _c.Operation("DELETE", success=UnassignProjectGroupRole200, errors={400: ('UnassignProjectGroupRole400', UnassignProjectGroupRole400), 403: ('UnassignProjectGroupRole403', UnassignProjectGroupRole403), 404: ('UnassignProjectGroupRole404', UnassignProjectGroupRole404), 429: ('UnassignProjectGroupRole429', UnassignProjectGroupRole429)})
_LIST_PROJECT_ROLES = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListProjectRoles200, errors={400: ('ListProjectRoles400', ListProjectRoles400), 403: ('ListProjectRoles403', ListProjectRoles403), 404: ('ListProjectRoles404', ListProjectRoles404), 429: ('ListProjectRoles429', ListProjectRoles429)})
_CREATE_PROJECT_ROLE = _c.Operation("POST", success=CreateProjectRole200, errors={400: ('CreateProjectRole400', CreateProjectRole400), 403: ('CreateProjectRole403', CreateProjectRole403), 404: ('CreateProjectRole404', CreateProjectRole404), 429: ('CreateProjectRole429', CreateProjectRole429)})
_RETRIEVE_PROJECT_ROLE = _c.Operation("GET", success=RetrieveProjectRole200, errors={403: ('RetrieveProjectRole403', RetrieveProjectRole403), 404: ('RetrieveProjectRole404', RetrieveProjectRole404), 429: ('RetrieveProjectRole429', RetrieveProjectRole429)})
_UPDATE_PROJECT_ROLE = _c.Operation("POST", success=UpdateProjectRole200, errors={400: ('UpdateProjectRole400', UpdateProjectRole400), 403: ('UpdateProjectRole403', UpdateProjectRole403), 404: ('UpdateProjectRole404', UpdateProjectRole404), 429: ('UpdateProjectRole429', UpdateProjectRole429)})
_DELETE_PROJECT_ROLE = _c.Operation("DELETE", success=DeleteProjectRole200, errors={400: ('DeleteProjectRole400', DeleteProjectRole400), 403: ('DeleteProjectRole403', DeleteProjectRole403), 404: ('DeleteProjectRole404', DeleteProjectRole404), 429: ('DeleteProjectRole429', DeleteProjectRole429)})
_LIST_PROJECT_USER_ROLE_ASSIGNMENTS = _c.Operation("GET", url_params=('limit', 'after', 'order', ), success=ListProjectUserRoleAssignments200, errors={400: ('ListProjectUserRoleAssignments400', ListProjectUserRoleAssignments400), 403: ('ListProjectUserRoleAssignments403', ListProjectUserRoleAssignments403), 404: ('ListProjectUserRoleAssignments404', ListProjectUserRoleAssignments404), 429: ('ListProjectUserRoleAssignments429', ListProjectUserRoleAssignments429)})
_ASSIGN_PROJECT_USER_ROLE = _c.Operation("POST", success=AssignProjectUserRole200, errors={400: ('AssignProjectUserRole400', AssignProjectUserRole400), 403: ('AssignProjectUserRole403', AssignProjectUserRole403), 404: ('AssignProjectUserRole404', AssignProjectUserRole404), 429: ('AssignProjectUserRole429', AssignProjectUserRole429)})
_RETRIEVE_PROJECT_USER_ROLE = _c.Operation("GET", success=RetrieveProjectUserRole200, errors={400: ('RetrieveProjectUserRole400', RetrieveProjectUserRole400), 403: ('RetrieveProjectUserRole403', RetrieveProjectUserRole403), 404: ('RetrieveProjectUserRole404', RetrieveProjectUserRole404), 429: ('RetrieveProjectUserRole429', RetrieveProjectUserRole429)})
_UNASSIGN_PROJECT_USER_ROLE = _c.Operation("DELETE", success=UnassignProjectUserRole200, errors={400: ('UnassignProjectUserRole400', UnassignProjectUserRole400), 403: ('UnassignProjectUserRole403', UnassignProjectUserRole403), 404: ('UnassignProjectUserRole404', UnassignProjectUserRole404), 429: ('UnassignProjectUserRole429', UnassignProjectUserRole429)})
_CREATE_REALTIME_CALL = _c.Operation("POST")
_ACCEPT_REALTIME_CALL = _c.Operation("POST", void=(200, ), errors={404: ('AcceptRealtimeCall404', AcceptRealtimeCall404), 409: ('AcceptRealtimeCall409', AcceptRealtimeCall409)})
_HANGUP_REALTIME_CALL = _c.Operation("POST", void=(200, ), errors={404: ('HangupRealtimeCall404', HangupRealtimeCall404)})
_REFER_REALTIME_CALL = _c.Operation("POST", void=(200, ), errors={404: ('ReferRealtimeCall404', ReferRealtimeCall404)})
_REJECT_REALTIME_CALL = _c.Operation("POST", void=(200, ), errors={404: ('RejectRealtimeCall404', RejectRealtimeCall404), 409: ('RejectRealtimeCall409', RejectRealtimeCall409)})
_CREATE_REALTIME_CLIENT_SECRET = _c.Operation("POST", success=CreateRealtimeClientSecret200, errors={400: ('CreateRealtimeClientSecret400', CreateRealtimeClientSecret400), 404: ('CreateRealtimeClientSecret404', CreateRealtimeClientSecret404), 500: ('CreateRealtimeClientSecret500', CreateRealtimeClientSecret500)})
_CREATE_REALTIME_SESSION = _c.Operation("POST", success=CreateRealtimeSession200)
_CREATE_REALTIME_TRANSCRIPTION_SESSION = _c.Operation("POST", success=CreateRealtimeTranscriptionSession200)
_CREATE_REALTIME_TRANSLATION_CLIENT_SECRET = _c.Operation("POST", success=CreateRealtimeTranslationClientSecret200, errors={400: ('CreateRealtimeTranslationClientSecret400', CreateRealtimeTranslationClientSecret400), 404: ('CreateRealtimeTranslationClientSecret404', CreateRealtimeTranslationClientSecret404), 500: ('CreateRealtimeTranslationClientSecret500', CreateRealtimeTranslationClientSecret500)})
_CREATE_RESPONSE = _c.Operation("POST", success=CreateResponse200, errors={400: ('CreateResponse400', CreateResponse400), 404: ('CreateResponse404', CreateResponse404), 429: ('CreateResponse429', CreateResponse429), 503: ('CreateResponse503', CreateResponse503)})
_CREATE_RESPONSE_SSE = _c.Operation("POST")
_GET_RESPONSE = _c.Operation("GET", url_params=('include', 'stream', 'starting_after', 'include_obfuscation', ), success=GetResponse200, errors={404: ('GetResponse404', GetResponse404), 429: ('GetResponse429', GetResponse429)})
_DELETE_RESPONSE = _c.Operation("DELETE", success=DeleteResponse200, errors={404: ('DeleteResponse404', DeleteResponse404), 429: ('DeleteResponse429', DeleteResponse429)})
_CANCEL_RESPONSE = _c.Operation("POST", success=CancelResponse200, errors={404: ('CancelResponse404', CancelResponse404), 429: ('CancelResponse429', CancelResponse429)})
_LIST_INPUT_ITEMS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'include', ), success=ListInputItems200, errors={404: ('ListInputItems404', ListInputItems404), 429: ('ListInputItems429', ListInputItems429)})
_CREATE_THREAD = _c.Operation("POST", success=CreateThread200, errors={429: ('CreateThread429', CreateThread429)})
_CREATE_THREAD_AND_RUN = _c.Operation("POST", success=CreateThreadAndRun200, errors={429: ('CreateThreadAndRun429', CreateThreadAndRun429)})
_CREATE_THREAD_AND_RUN_SSE = _c.Operation("POST")
_GET_THREAD = _c.Operation("GET", success=GetThread200, errors={429: ('GetThread429', GetThread429)})
_MODIFY_THREAD = _c.Operation("POST", success=ModifyThread200, errors={429: ('ModifyThread429', ModifyThread429)})
_DELETE_THREAD = _c.Operation("DELETE", success=DeleteThread200, errors={429: ('DeleteThread429', DeleteThread429)})
_LIST_MESSAGES = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', 'run_id', ), success=ListMessages200, errors={429: ('ListMessages429', ListMessages429)})
_CREATE_MESSAGE = _c.Operation("POST", success=CreateMessage200, errors={429: ('CreateMessage429', CreateMessage429)})
_GET_MESSAGE = _c.Operation("GET", success=GetMessage200, errors={429: ('GetMessage429', GetMessage429)})
_MODIFY_MESSAGE = _c.Operation("POST", success=ModifyMessage200, errors={429: ('ModifyMessage429', ModifyMessage429)})
_DELETE_MESSAGE = _c.Operation("DELETE", success=DeleteMessage200, errors={429: ('DeleteMessage429', DeleteMessage429)})
_LIST_RUNS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', ), success=ListRuns200, errors={429: ('ListRuns429', ListRuns429)})
_CREATE_RUN = _c.Operation("POST", url_params=('include[]', ), success=CreateRun200, errors={429: ('CreateRun429', CreateRun429)})
_CREATE_RUN_SSE = _c.Operation("POST", url_params=('include[]', ))
_GET_RUN = _c.Operation("GET", success=GetRun200, errors={429: ('GetRun429', GetRun429)})
_MODIFY_RUN = _c.Operation("POST", success=ModifyRun200, errors={429: ('ModifyRun429', ModifyRun429)})
_CANCEL_RUN = _c.Operation("POST", success=CancelRun200, errors={429: ('CancelRun429', CancelRun429)})
_LIST_RUN_STEPS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', 'include[]', ), success=ListRunSteps200, errors={429: ('ListRunSteps429', ListRunSteps429)})
_GET_RUN_STEP = _c.Operation("GET", url_params=('include[]', ), success=GetRunStep200, errors={429: ('GetRunStep429', GetRunStep429)})
_SUBMIT_TOOL_OUPUTS_TO_RUN = _c.Operation("POST", success=SubmitToolOuputsToRun200, errors={429: ('SubmitToolOuputsToRun429', SubmitToolOuputsToRun429)})
_SUBMIT_TOOL_OUPUTS_TO_RUN_SSE = _c.Operation("POST")
_CREATE_UPLOAD = _c.Operation("POST", success=CreateUpload200, errors={400: ('CreateUpload400', CreateUpload400), 429: ('CreateUpload429', CreateUpload429)})
_CANCEL_UPLOAD = _c.Operation("POST", success=CancelUpload200, errors={400: ('CancelUpload400', CancelUpload400), 404: ('CancelUpload404', CancelUpload404), 410: ('CancelUpload410', CancelUpload410), 429: ('CancelUpload429', CancelUpload429)})
_COMPLETE_UPLOAD = _c.Operation("POST", success=CompleteUpload200, errors={400: ('CompleteUpload400', CompleteUpload400), 404: ('CompleteUpload404', CompleteUpload404), 410: ('CompleteUpload410', CompleteUpload410), 429: ('CompleteUpload429', CompleteUpload429), 500: ('CompleteUpload500', CompleteUpload500)})
_ADD_UPLOAD_PART = _c.Operation("POST", success=AddUploadPart200, errors={400: ('AddUploadPart400', AddUploadPart400), 404: ('AddUploadPart404', AddUploadPart404), 410: ('AddUploadPart410', AddUploadPart410), 429: ('AddUploadPart429', AddUploadPart429), 500: ('AddUploadPart500', AddUploadPart500)})
_LIST_VECTOR_STORES = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', ), success=ListVectorStores200, errors={429: ('ListVectorStores429', ListVectorStores429), 503: ('ListVectorStores503', ListVectorStores503)})
_CREATE_VECTOR_STORE = _c.Operation("POST", success=CreateVectorStore200, errors={400: ('CreateVectorStore400', CreateVectorStore400), 404: ('CreateVectorStore404', CreateVectorStore404), 429: ('CreateVectorStore429', CreateVectorStore429)})
_GET_VECTOR_STORE = _c.Operation("GET", success=GetVectorStore200, errors={404: ('GetVectorStore404', GetVectorStore404), 429: ('GetVectorStore429', GetVectorStore429)})
_MODIFY_VECTOR_STORE = _c.Operation("POST", success=ModifyVectorStore200, errors={400: ('ModifyVectorStore400', ModifyVectorStore400), 403: ('ModifyVectorStore403', ModifyVectorStore403), 404: ('ModifyVectorStore404', ModifyVectorStore404), 429: ('ModifyVectorStore429', ModifyVectorStore429)})
_DELETE_VECTOR_STORE = _c.Operation("DELETE", success=DeleteVectorStore200, errors={404: ('DeleteVectorStore404', DeleteVectorStore404), 409: ('DeleteVectorStore409', DeleteVectorStore409), 429: ('DeleteVectorStore429', DeleteVectorStore429)})
_CREATE_VECTOR_STORE_FILE_BATCH = _c.Operation("POST", success=CreateVectorStoreFileBatch200, errors={400: ('CreateVectorStoreFileBatch400', CreateVectorStoreFileBatch400), 404: ('CreateVectorStoreFileBatch404', CreateVectorStoreFileBatch404), 409: ('CreateVectorStoreFileBatch409', CreateVectorStoreFileBatch409), 429: ('CreateVectorStoreFileBatch429', CreateVectorStoreFileBatch429), 500: ('CreateVectorStoreFileBatch500', CreateVectorStoreFileBatch500)})
_GET_VECTOR_STORE_FILE_BATCH = _c.Operation("GET", success=GetVectorStoreFileBatch200, errors={400: ('GetVectorStoreFileBatch400', GetVectorStoreFileBatch400), 404: ('GetVectorStoreFileBatch404', GetVectorStoreFileBatch404), 429: ('GetVectorStoreFileBatch429', GetVectorStoreFileBatch429)})
_CANCEL_VECTOR_STORE_FILE_BATCH = _c.Operation("POST", success=CancelVectorStoreFileBatch200, errors={400: ('CancelVectorStoreFileBatch400', CancelVectorStoreFileBatch400), 404: ('CancelVectorStoreFileBatch404', CancelVectorStoreFileBatch404), 409: ('CancelVectorStoreFileBatch409', CancelVectorStoreFileBatch409), 429: ('CancelVectorStoreFileBatch429', CancelVectorStoreFileBatch429)})
_LIST_FILES_IN_VECTOR_STORE_BATCH = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', 'filter', ), success=ListFilesInVectorStoreBatch200, errors={400: ('ListFilesInVectorStoreBatch400', ListFilesInVectorStoreBatch400), 404: ('ListFilesInVectorStoreBatch404', ListFilesInVectorStoreBatch404), 429: ('ListFilesInVectorStoreBatch429', ListFilesInVectorStoreBatch429)})
_LIST_VECTOR_STORE_FILES = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', 'filter', ), success=ListVectorStoreFiles200, errors={400: ('ListVectorStoreFiles400', ListVectorStoreFiles400), 404: ('ListVectorStoreFiles404', ListVectorStoreFiles404), 429: ('ListVectorStoreFiles429', ListVectorStoreFiles429)})
_CREATE_VECTOR_STORE_FILE = _c.Operation("POST", success=CreateVectorStoreFile200, errors={400: ('CreateVectorStoreFile400', CreateVectorStoreFile400), 404: ('CreateVectorStoreFile404', CreateVectorStoreFile404), 409: ('CreateVectorStoreFile409', CreateVectorStoreFile409), 429: ('CreateVectorStoreFile429', CreateVectorStoreFile429), 500: ('CreateVectorStoreFile500', CreateVectorStoreFile500)})
_GET_VECTOR_STORE_FILE = _c.Operation("GET", success=GetVectorStoreFile200, errors={404: ('GetVectorStoreFile404', GetVectorStoreFile404), 429: ('GetVectorStoreFile429', GetVectorStoreFile429), 500: ('GetVectorStoreFile500', GetVectorStoreFile500)})
_UPDATE_VECTOR_STORE_FILE_ATTRIBUTES = _c.Operation("POST", success=UpdateVectorStoreFileAttributes200, errors={400: ('UpdateVectorStoreFileAttributes400', UpdateVectorStoreFileAttributes400), 404: ('UpdateVectorStoreFileAttributes404', UpdateVectorStoreFileAttributes404), 409: ('UpdateVectorStoreFileAttributes409', UpdateVectorStoreFileAttributes409), 429: ('UpdateVectorStoreFileAttributes429', UpdateVectorStoreFileAttributes429), 500: ('UpdateVectorStoreFileAttributes500', UpdateVectorStoreFileAttributes500)})
_DELETE_VECTOR_STORE_FILE = _c.Operation("DELETE", success=DeleteVectorStoreFile200, errors={400: ('DeleteVectorStoreFile400', DeleteVectorStoreFile400), 404: ('DeleteVectorStoreFile404', DeleteVectorStoreFile404), 409: ('DeleteVectorStoreFile409', DeleteVectorStoreFile409), 429: ('DeleteVectorStoreFile429', DeleteVectorStoreFile429), 500: ('DeleteVectorStoreFile500', DeleteVectorStoreFile500)})
_RETRIEVE_VECTOR_STORE_FILE_CONTENT = _c.Operation("GET", success=RetrieveVectorStoreFileContent200, errors={400: ('RetrieveVectorStoreFileContent400', RetrieveVectorStoreFileContent400), 404: ('RetrieveVectorStoreFileContent404', RetrieveVectorStoreFileContent404), 429: ('RetrieveVectorStoreFileContent429', RetrieveVectorStoreFileContent429), 500: ('RetrieveVectorStoreFileContent500', RetrieveVectorStoreFileContent500)})
_SEARCH_VECTOR_STORE = _c.Operation("POST", success=SearchVectorStore200, errors={400: ('SearchVectorStore400', SearchVectorStore400), 404: ('SearchVectorStore404', SearchVectorStore404), 429: ('SearchVectorStore429', SearchVectorStore429)})
_CREATE_CONVERSATION = _c.Operation("POST", success=CreateConversation200, errors={400: ('CreateConversation400', CreateConversation400), 429: ('CreateConversation429', CreateConversation429), 500: ('CreateConversation500', CreateConversation500)})
_GET_CONVERSATION = _c.Operation("GET", success=GetConversation200, errors={404: ('GetConversation404', GetConversation404), 429: ('GetConversation429', GetConversation429)})
_UPDATE_CONVERSATION = _c.Operation("POST", success=UpdateConversation200, errors={400: ('UpdateConversation400', UpdateConversation400), 404: ('UpdateConversation404', UpdateConversation404), 429: ('UpdateConversation429', UpdateConversation429), 500: ('UpdateConversation500', UpdateConversation500)})
_DELETE_CONVERSATION = _c.Operation("DELETE", success=DeleteConversation200, errors={404: ('DeleteConversation404', DeleteConversation404), 429: ('DeleteConversation429', DeleteConversation429)})
_GETSAFETYCASE = _c.Operation("GET", success=Getsafetycase200, errors={400: ('Getsafetycase400', Getsafetycase400), 404: ('Getsafetycase404', Getsafetycase404), 429: ('Getsafetycase429', Getsafetycase429), 500: ('Getsafetycase500', Getsafetycase500), 503: ('Getsafetycase503', Getsafetycase503)})
_GETPROJECTSAFETYALERT = _c.Operation("GET", success=Getprojectsafetyalert200, errors={400: ('Getprojectsafetyalert400', Getprojectsafetyalert400), 404: ('Getprojectsafetyalert404', Getprojectsafetyalert404), 429: ('Getprojectsafetyalert429', Getprojectsafetyalert429), 503: ('Getprojectsafetyalert503', Getprojectsafetyalert503)})
_DOWNLOAD_LIVE_RECORDING = _c.Operation("GET", binary_success=True, errors={400: ('DownloadLiveRecording400', DownloadLiveRecording400), 404: ('DownloadLiveRecording404', DownloadLiveRecording404), 429: ('DownloadLiveRecording429', DownloadLiveRecording429), 500: ('DownloadLiveRecording500', DownloadLiveRecording500), 503: ('DownloadLiveRecording503', DownloadLiveRecording503)})
_DOWNLOAD_LIVE_RECORDING_STREAM = _c.Operation("GET")
_ORGANIZATION_DECISIONSUSAGE = _c.Operation("GET", url_params=('start_time', 'end_time', 'bucket_width', 'limit', 'page', 'project_ids', 'group_by', 'user_ids', 'api_key_ids', 'models', 'batch', ), success=OrganizationDecisionsusage200, errors={400: ('OrganizationDecisionsusage400', OrganizationDecisionsusage400), 403: ('OrganizationDecisionsusage403', OrganizationDecisionsusage403), 429: ('OrganizationDecisionsusage429', OrganizationDecisionsusage429)})
_LISTEXTERNALSTORAGECONFIGURATIONS = _c.Operation("GET", url_params=('project_id', 'after', 'order', 'limit', ), success=Listexternalstorageconfigurations200, errors={400: ('Listexternalstorageconfigurations400', Listexternalstorageconfigurations400), 403: ('Listexternalstorageconfigurations403', Listexternalstorageconfigurations403), 404: ('Listexternalstorageconfigurations404', Listexternalstorageconfigurations404)})
_CREATEANEXTERNALSTORAGECONFIGURATION = _c.Operation("POST", success=Createanexternalstorageconfiguration200, errors={400: ('Createanexternalstorageconfiguration400', Createanexternalstorageconfiguration400), 403: ('Createanexternalstorageconfiguration403', Createanexternalstorageconfiguration403), 404: ('Createanexternalstorageconfiguration404', Createanexternalstorageconfiguration404), 503: ('Createanexternalstorageconfiguration503', Createanexternalstorageconfiguration503)})
_GETANEXTERNALSTORAGECONFIGURATION = _c.Operation("GET", success=Getanexternalstorageconfiguration200, errors={400: ('Getanexternalstorageconfiguration400', Getanexternalstorageconfiguration400), 403: ('Getanexternalstorageconfiguration403', Getanexternalstorageconfiguration403), 404: ('Getanexternalstorageconfiguration404', Getanexternalstorageconfiguration404)})
_DELETEANEXTERNALSTORAGECONFIGURATION = _c.Operation("DELETE", success=Deleteanexternalstorageconfiguration200, errors={400: ('Deleteanexternalstorageconfiguration400', Deleteanexternalstorageconfiguration400), 403: ('Deleteanexternalstorageconfiguration403', Deleteanexternalstorageconfiguration403), 404: ('Deleteanexternalstorageconfiguration404', Deleteanexternalstorageconfiguration404)})
_VALIDATEANEXTERNALSTORAGECONFIGURATION = _c.Operation("POST", success=Validateanexternalstorageconfiguration200, errors={400: ('Validateanexternalstorageconfiguration400', Validateanexternalstorageconfiguration400), 403: ('Validateanexternalstorageconfiguration403', Validateanexternalstorageconfiguration403), 404: ('Validateanexternalstorageconfiguration404', Validateanexternalstorageconfiguration404), 503: ('Validateanexternalstorageconfiguration503', Validateanexternalstorageconfiguration503)})
_GETORGANIZATIONSPENDLIMIT = _c.Operation("GET", success=Getorganizationspendlimit200, errors={403: ('Getorganizationspendlimit403', Getorganizationspendlimit403), 404: ('Getorganizationspendlimit404', Getorganizationspendlimit404)})
_UPDATEORGANIZATIONSPENDLIMIT = _c.Operation("POST", success=Updateorganizationspendlimit200, errors={400: ('Updateorganizationspendlimit400', Updateorganizationspendlimit400), 403: ('Updateorganizationspendlimit403', Updateorganizationspendlimit403)})
_DELETEORGANIZATIONSPENDLIMIT = _c.Operation("DELETE", success=Deleteorganizationspendlimit200, errors={403: ('Deleteorganizationspendlimit403', Deleteorganizationspendlimit403), 404: ('Deleteorganizationspendlimit404', Deleteorganizationspendlimit404)})
_GETPROJECTSPENDLIMIT = _c.Operation("GET", success=Getprojectspendlimit200, errors={400: ('Getprojectspendlimit400', Getprojectspendlimit400), 403: ('Getprojectspendlimit403', Getprojectspendlimit403), 404: ('Getprojectspendlimit404', Getprojectspendlimit404)})
_UPDATEPROJECTSPENDLIMIT = _c.Operation("POST", success=Updateprojectspendlimit200, errors={400: ('Updateprojectspendlimit400', Updateprojectspendlimit400), 403: ('Updateprojectspendlimit403', Updateprojectspendlimit403), 404: ('Updateprojectspendlimit404', Updateprojectspendlimit404)})
_DELETEPROJECTSPENDLIMIT = _c.Operation("DELETE", success=Deleteprojectspendlimit200, errors={400: ('Deleteprojectspendlimit400', Deleteprojectspendlimit400), 403: ('Deleteprojectspendlimit403', Deleteprojectspendlimit403), 404: ('Deleteprojectspendlimit404', Deleteprojectspendlimit404)})
_CREATEAN_AP_IKEYFORASERVICEACCOUNT = _c.Operation("POST", success=CreateanAPIkeyforaserviceaccount200, errors={400: ('CreateanAPIkeyforaserviceaccount400', CreateanAPIkeyforaserviceaccount400), 403: ('CreateanAPIkeyforaserviceaccount403', CreateanAPIkeyforaserviceaccount403), 404: ('CreateanAPIkeyforaserviceaccount404', CreateanAPIkeyforaserviceaccount404), 409: ('CreateanAPIkeyforaserviceaccount409', CreateanAPIkeyforaserviceaccount409), 429: ('CreateanAPIkeyforaserviceaccount429', CreateanAPIkeyforaserviceaccount429)})
_CREATECONTENTPROVENANCECHECK = _c.Operation("POST", success=Createcontentprovenancecheck200, errors={400: ('Createcontentprovenancecheck400', Createcontentprovenancecheck400), 404: ('Createcontentprovenancecheck404', Createcontentprovenancecheck404), 429: ('Createcontentprovenancecheck429', Createcontentprovenancecheck429), 500: ('Createcontentprovenancecheck500', Createcontentprovenancecheck500), 503: ('Createcontentprovenancecheck503', Createcontentprovenancecheck503)})
_LIST_VIDEOS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListVideos200, errors={400: ('ListVideos400', ListVideos400), 404: ('ListVideos404', ListVideos404)})
_CREATE_VIDEO = _c.Operation("POST", success=CreateVideo200, errors={400: ('CreateVideo400', CreateVideo400), 404: ('CreateVideo404', CreateVideo404), 429: ('CreateVideo429', CreateVideo429), 500: ('CreateVideo500', CreateVideo500), 503: ('CreateVideo503', CreateVideo503)})
_CREATE_VIDEO_CHARACTER = _c.Operation("POST", success=CreateVideoCharacter200, errors={400: ('CreateVideoCharacter400', CreateVideoCharacter400), 404: ('CreateVideoCharacter404', CreateVideoCharacter404), 500: ('CreateVideoCharacter500', CreateVideoCharacter500), 504: ('CreateVideoCharacter504', CreateVideoCharacter504)})
_GET_VIDEO_CHARACTER = _c.Operation("GET", success=GetVideoCharacter200, errors={400: ('GetVideoCharacter400', GetVideoCharacter400), 404: ('GetVideoCharacter404', GetVideoCharacter404)})
_CREATE_VIDEO_EDIT = _c.Operation("POST", success=CreateVideoEdit200, errors={400: ('CreateVideoEdit400', CreateVideoEdit400), 404: ('CreateVideoEdit404', CreateVideoEdit404), 429: ('CreateVideoEdit429', CreateVideoEdit429), 500: ('CreateVideoEdit500', CreateVideoEdit500), 503: ('CreateVideoEdit503', CreateVideoEdit503)})
_CREATE_VIDEO_EXTEND = _c.Operation("POST", success=CreateVideoExtend200, errors={400: ('CreateVideoExtend400', CreateVideoExtend400), 404: ('CreateVideoExtend404', CreateVideoExtend404), 429: ('CreateVideoExtend429', CreateVideoExtend429), 500: ('CreateVideoExtend500', CreateVideoExtend500), 503: ('CreateVideoExtend503', CreateVideoExtend503)})
_GET_VIDEO = _c.Operation("GET", success=GetVideo200, errors={400: ('GetVideo400', GetVideo400), 404: ('GetVideo404', GetVideo404)})
_DELETE_VIDEO = _c.Operation("DELETE", success=DeleteVideo200, errors={400: ('DeleteVideo400', DeleteVideo400), 404: ('DeleteVideo404', DeleteVideo404), 500: ('DeleteVideo500', DeleteVideo500)})
_RETRIEVE_VIDEO_CONTENT = _c.Operation("GET", url_params=('variant', ), binary_success=True, errors={400: ('RetrieveVideoContent400', RetrieveVideoContent400), 404: ('RetrieveVideoContent404', RetrieveVideoContent404), 500: ('RetrieveVideoContent500', RetrieveVideoContent500)})
_RETRIEVE_VIDEO_CONTENT_STREAM = _c.Operation("GET", url_params=('variant', ))
_CREATE_VIDEO_REMIX = _c.Operation("POST", success=CreateVideoRemix200, errors={400: ('CreateVideoRemix400', CreateVideoRemix400), 404: ('CreateVideoRemix404', CreateVideoRemix404), 429: ('CreateVideoRemix429', CreateVideoRemix429), 500: ('CreateVideoRemix500', CreateVideoRemix500), 503: ('CreateVideoRemix503', CreateVideoRemix503)})
_GETINPUTTOKENCOUNTS = _c.Operation("POST", success=Getinputtokencounts200, errors={400: ('Getinputtokencounts400', Getinputtokencounts400), 429: ('Getinputtokencounts429', Getinputtokencounts429)})
_COMPACTCONVERSATION = _c.Operation("POST", success=Compactconversation200, errors={400: ('Compactconversation400', Compactconversation400), 429: ('Compactconversation429', Compactconversation429), 503: ('Compactconversation503', Compactconversation503)})
_LIST_SKILLS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListSkills200, errors={404: ('ListSkills404', ListSkills404), 429: ('ListSkills429', ListSkills429)})
_CREATE_SKILL = _c.Operation("POST", success=CreateSkill200, errors={400: ('CreateSkill400', CreateSkill400), 429: ('CreateSkill429', CreateSkill429), 500: ('CreateSkill500', CreateSkill500)})
_GET_SKILL = _c.Operation("GET", success=GetSkill200, errors={404: ('GetSkill404', GetSkill404), 429: ('GetSkill429', GetSkill429)})
_UPDATE_SKILL_DEFAULT_VERSION = _c.Operation("POST", success=UpdateSkillDefaultVersion200, errors={400: ('UpdateSkillDefaultVersion400', UpdateSkillDefaultVersion400), 404: ('UpdateSkillDefaultVersion404', UpdateSkillDefaultVersion404), 429: ('UpdateSkillDefaultVersion429', UpdateSkillDefaultVersion429)})
_DELETE_SKILL = _c.Operation("DELETE", success=DeleteSkill200, errors={404: ('DeleteSkill404', DeleteSkill404), 429: ('DeleteSkill429', DeleteSkill429)})
_GET_SKILL_CONTENT = _c.Operation("GET", binary_success=True, errors={404: ('GetSkillContent404', GetSkillContent404), 429: ('GetSkillContent429', GetSkillContent429)})
_GET_SKILL_CONTENT_STREAM = _c.Operation("GET")
_LIST_SKILL_VERSIONS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListSkillVersions200, errors={400: ('ListSkillVersions400', ListSkillVersions400), 404: ('ListSkillVersions404', ListSkillVersions404), 429: ('ListSkillVersions429', ListSkillVersions429)})
_CREATE_SKILL_VERSION = _c.Operation("POST", success=CreateSkillVersion200, errors={400: ('CreateSkillVersion400', CreateSkillVersion400), 404: ('CreateSkillVersion404', CreateSkillVersion404), 429: ('CreateSkillVersion429', CreateSkillVersion429), 500: ('CreateSkillVersion500', CreateSkillVersion500)})
_GET_SKILL_VERSION = _c.Operation("GET", success=GetSkillVersion200, errors={400: ('GetSkillVersion400', GetSkillVersion400), 404: ('GetSkillVersion404', GetSkillVersion404), 429: ('GetSkillVersion429', GetSkillVersion429)})
_DELETE_SKILL_VERSION = _c.Operation("DELETE", success=DeleteSkillVersion200, errors={400: ('DeleteSkillVersion400', DeleteSkillVersion400), 404: ('DeleteSkillVersion404', DeleteSkillVersion404), 429: ('DeleteSkillVersion429', DeleteSkillVersion429)})
_GET_SKILL_VERSION_CONTENT = _c.Operation("GET", binary_success=True, errors={400: ('GetSkillVersionContent400', GetSkillVersionContent400), 404: ('GetSkillVersionContent404', GetSkillVersionContent404), 429: ('GetSkillVersionContent429', GetSkillVersionContent429)})
_GET_SKILL_VERSION_CONTENT_STREAM = _c.Operation("GET")
_CANCEL_CHAT_SESSION_METHOD = _c.Operation("POST", success=CancelChatSessionMethod200, errors={400: ('CancelChatSessionMethod400', CancelChatSessionMethod400), 404: ('CancelChatSessionMethod404', CancelChatSessionMethod404), 429: ('CancelChatSessionMethod429', CancelChatSessionMethod429)})
_CREATE_CHAT_SESSION_METHOD = _c.Operation("POST", success=CreateChatSessionMethod200, errors={400: ('CreateChatSessionMethod400', CreateChatSessionMethod400), 404: ('CreateChatSessionMethod404', CreateChatSessionMethod404), 429: ('CreateChatSessionMethod429', CreateChatSessionMethod429)})
_LIST_THREAD_ITEMS_METHOD = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', ), success=ListThreadItemsMethod200, errors={400: ('ListThreadItemsMethod400', ListThreadItemsMethod400), 404: ('ListThreadItemsMethod404', ListThreadItemsMethod404), 429: ('ListThreadItemsMethod429', ListThreadItemsMethod429)})
_GET_THREAD_METHOD = _c.Operation("GET", success=GetThreadMethod200, errors={400: ('GetThreadMethod400', GetThreadMethod400), 404: ('GetThreadMethod404', GetThreadMethod404), 429: ('GetThreadMethod429', GetThreadMethod429)})
_DELETE_THREAD_METHOD = _c.Operation("DELETE", success=DeleteThreadMethod200, errors={400: ('DeleteThreadMethod400', DeleteThreadMethod400), 404: ('DeleteThreadMethod404', DeleteThreadMethod404), 429: ('DeleteThreadMethod429', DeleteThreadMethod429)})
_LIST_THREADS_METHOD = _c.Operation("GET", url_params=('limit', 'order', 'after', 'before', 'user', ), success=ListThreadsMethod200, errors={400: ('ListThreadsMethod400', ListThreadsMethod400), 404: ('ListThreadsMethod404', ListThreadsMethod404), 429: ('ListThreadsMethod429', ListThreadsMethod429)})
_CREATE_DECISION = _c.Operation("POST", success=CreateDecision200)
_LIST_AGENT_ENVIRONMENTS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'type', ), success=ListAgentEnvironments200, errors={400: ('ListAgentEnvironments400', ListAgentEnvironments400), 401: ('ListAgentEnvironments401', ListAgentEnvironments401), 403: ('ListAgentEnvironments403', ListAgentEnvironments403), 404: ('ListAgentEnvironments404', ListAgentEnvironments404), 409: ('ListAgentEnvironments409', ListAgentEnvironments409), 500: ('ListAgentEnvironments500', ListAgentEnvironments500), 503: ('ListAgentEnvironments503', ListAgentEnvironments503)})
_CREATE_AGENT_ENVIRONMENT = _c.Operation("POST", headers=('Idempotency-Key', ), success=CreateAgentEnvironment201, errors={400: ('CreateAgentEnvironment400', CreateAgentEnvironment400), 401: ('CreateAgentEnvironment401', CreateAgentEnvironment401), 403: ('CreateAgentEnvironment403', CreateAgentEnvironment403), 404: ('CreateAgentEnvironment404', CreateAgentEnvironment404), 409: ('CreateAgentEnvironment409', CreateAgentEnvironment409), 429: ('CreateAgentEnvironment429', CreateAgentEnvironment429), 500: ('CreateAgentEnvironment500', CreateAgentEnvironment500), 503: ('CreateAgentEnvironment503', CreateAgentEnvironment503)})
_RETRIEVE_AGENT_ENVIRONMENT = _c.Operation("GET", success=RetrieveAgentEnvironment200, errors={400: ('RetrieveAgentEnvironment400', RetrieveAgentEnvironment400), 401: ('RetrieveAgentEnvironment401', RetrieveAgentEnvironment401), 403: ('RetrieveAgentEnvironment403', RetrieveAgentEnvironment403), 404: ('RetrieveAgentEnvironment404', RetrieveAgentEnvironment404), 409: ('RetrieveAgentEnvironment409', RetrieveAgentEnvironment409), 500: ('RetrieveAgentEnvironment500', RetrieveAgentEnvironment500), 503: ('RetrieveAgentEnvironment503', RetrieveAgentEnvironment503)})
_LIST_AGENT_ENVIRONMENT_FILES = _c.Operation("GET", url_params=('path', 'limit', 'order', 'page', ), success=ListAgentEnvironmentFiles200, errors={400: ('ListAgentEnvironmentFiles400', ListAgentEnvironmentFiles400), 401: ('ListAgentEnvironmentFiles401', ListAgentEnvironmentFiles401), 403: ('ListAgentEnvironmentFiles403', ListAgentEnvironmentFiles403), 404: ('ListAgentEnvironmentFiles404', ListAgentEnvironmentFiles404), 409: ('ListAgentEnvironmentFiles409', ListAgentEnvironmentFiles409), 500: ('ListAgentEnvironmentFiles500', ListAgentEnvironmentFiles500), 503: ('ListAgentEnvironmentFiles503', ListAgentEnvironmentFiles503)})
_CREATE_AGENT_ENVIRONMENT_FILE = _c.Operation("POST", success=CreateAgentEnvironmentFile201, errors={400: ('CreateAgentEnvironmentFile400', CreateAgentEnvironmentFile400), 401: ('CreateAgentEnvironmentFile401', CreateAgentEnvironmentFile401), 403: ('CreateAgentEnvironmentFile403', CreateAgentEnvironmentFile403), 404: ('CreateAgentEnvironmentFile404', CreateAgentEnvironmentFile404), 409: ('CreateAgentEnvironmentFile409', CreateAgentEnvironmentFile409), 429: ('CreateAgentEnvironmentFile429', CreateAgentEnvironmentFile429), 500: ('CreateAgentEnvironmentFile500', CreateAgentEnvironmentFile500), 503: ('CreateAgentEnvironmentFile503', CreateAgentEnvironmentFile503)})
_LIST_AGENT_SESSION_SUBAGENTS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListAgentSessionSubagents200, errors={400: ('ListAgentSessionSubagents400', ListAgentSessionSubagents400), 401: ('ListAgentSessionSubagents401', ListAgentSessionSubagents401), 403: ('ListAgentSessionSubagents403', ListAgentSessionSubagents403), 404: ('ListAgentSessionSubagents404', ListAgentSessionSubagents404), 409: ('ListAgentSessionSubagents409', ListAgentSessionSubagents409), 500: ('ListAgentSessionSubagents500', ListAgentSessionSubagents500), 503: ('ListAgentSessionSubagents503', ListAgentSessionSubagents503)})
_RETRIEVE_AGENT_SESSION_SUBAGENT = _c.Operation("GET", success=RetrieveAgentSessionSubagent200, errors={400: ('RetrieveAgentSessionSubagent400', RetrieveAgentSessionSubagent400), 401: ('RetrieveAgentSessionSubagent401', RetrieveAgentSessionSubagent401), 403: ('RetrieveAgentSessionSubagent403', RetrieveAgentSessionSubagent403), 404: ('RetrieveAgentSessionSubagent404', RetrieveAgentSessionSubagent404), 409: ('RetrieveAgentSessionSubagent409', RetrieveAgentSessionSubagent409), 500: ('RetrieveAgentSessionSubagent500', RetrieveAgentSessionSubagent500), 503: ('RetrieveAgentSessionSubagent503', RetrieveAgentSessionSubagent503)})
_LIST_AGENT_SESSION_SUBAGENT_ITEMS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListAgentSessionSubagentItems200, errors={400: ('ListAgentSessionSubagentItems400', ListAgentSessionSubagentItems400), 401: ('ListAgentSessionSubagentItems401', ListAgentSessionSubagentItems401), 403: ('ListAgentSessionSubagentItems403', ListAgentSessionSubagentItems403), 404: ('ListAgentSessionSubagentItems404', ListAgentSessionSubagentItems404), 409: ('ListAgentSessionSubagentItems409', ListAgentSessionSubagentItems409), 500: ('ListAgentSessionSubagentItems500', ListAgentSessionSubagentItems500), 503: ('ListAgentSessionSubagentItems503', ListAgentSessionSubagentItems503)})
_LIST_AGENT_SESSION_SUBAGENT_TURNS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListAgentSessionSubagentTurns200, errors={400: ('ListAgentSessionSubagentTurns400', ListAgentSessionSubagentTurns400), 401: ('ListAgentSessionSubagentTurns401', ListAgentSessionSubagentTurns401), 403: ('ListAgentSessionSubagentTurns403', ListAgentSessionSubagentTurns403), 404: ('ListAgentSessionSubagentTurns404', ListAgentSessionSubagentTurns404), 409: ('ListAgentSessionSubagentTurns409', ListAgentSessionSubagentTurns409), 500: ('ListAgentSessionSubagentTurns500', ListAgentSessionSubagentTurns500), 503: ('ListAgentSessionSubagentTurns503', ListAgentSessionSubagentTurns503)})
_RETRIEVE_AGENT_SESSION_SUBAGENT_TURN = _c.Operation("GET", success=RetrieveAgentSessionSubagentTurn200, errors={400: ('RetrieveAgentSessionSubagentTurn400', RetrieveAgentSessionSubagentTurn400), 401: ('RetrieveAgentSessionSubagentTurn401', RetrieveAgentSessionSubagentTurn401), 403: ('RetrieveAgentSessionSubagentTurn403', RetrieveAgentSessionSubagentTurn403), 404: ('RetrieveAgentSessionSubagentTurn404', RetrieveAgentSessionSubagentTurn404), 409: ('RetrieveAgentSessionSubagentTurn409', RetrieveAgentSessionSubagentTurn409), 500: ('RetrieveAgentSessionSubagentTurn500', RetrieveAgentSessionSubagentTurn500), 503: ('RetrieveAgentSessionSubagentTurn503', RetrieveAgentSessionSubagentTurn503)})
_LIST_AGENT_SESSION_SUBAGENT_TURN_ITEMS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListAgentSessionSubagentTurnItems200, errors={400: ('ListAgentSessionSubagentTurnItems400', ListAgentSessionSubagentTurnItems400), 401: ('ListAgentSessionSubagentTurnItems401', ListAgentSessionSubagentTurnItems401), 403: ('ListAgentSessionSubagentTurnItems403', ListAgentSessionSubagentTurnItems403), 404: ('ListAgentSessionSubagentTurnItems404', ListAgentSessionSubagentTurnItems404), 409: ('ListAgentSessionSubagentTurnItems409', ListAgentSessionSubagentTurnItems409), 500: ('ListAgentSessionSubagentTurnItems500', ListAgentSessionSubagentTurnItems500), 503: ('ListAgentSessionSubagentTurnItems503', ListAgentSessionSubagentTurnItems503)})
_LIST_AGENTS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListAgents200, errors={400: ('ListAgents400', ListAgents400), 401: ('ListAgents401', ListAgents401), 403: ('ListAgents403', ListAgents403), 404: ('ListAgents404', ListAgents404), 409: ('ListAgents409', ListAgents409), 500: ('ListAgents500', ListAgents500), 503: ('ListAgents503', ListAgents503)})
_CREATE_AGENT = _c.Operation("POST", success=CreateAgent201, errors={400: ('CreateAgent400', CreateAgent400), 401: ('CreateAgent401', CreateAgent401), 403: ('CreateAgent403', CreateAgent403), 404: ('CreateAgent404', CreateAgent404), 409: ('CreateAgent409', CreateAgent409), 500: ('CreateAgent500', CreateAgent500), 503: ('CreateAgent503', CreateAgent503)})
_RETRIEVE_AGENT = _c.Operation("GET", success=RetrieveAgent200, errors={400: ('RetrieveAgent400', RetrieveAgent400), 401: ('RetrieveAgent401', RetrieveAgent401), 403: ('RetrieveAgent403', RetrieveAgent403), 404: ('RetrieveAgent404', RetrieveAgent404), 409: ('RetrieveAgent409', RetrieveAgent409), 500: ('RetrieveAgent500', RetrieveAgent500), 503: ('RetrieveAgent503', RetrieveAgent503)})
_UPDATE_AGENT = _c.Operation("POST", success=UpdateAgent200, errors={400: ('UpdateAgent400', UpdateAgent400), 401: ('UpdateAgent401', UpdateAgent401), 403: ('UpdateAgent403', UpdateAgent403), 404: ('UpdateAgent404', UpdateAgent404), 409: ('UpdateAgent409', UpdateAgent409), 500: ('UpdateAgent500', UpdateAgent500), 503: ('UpdateAgent503', UpdateAgent503)})
_DELETE_AGENT = _c.Operation("DELETE", success=DeleteAgent200, errors={400: ('DeleteAgent400', DeleteAgent400), 401: ('DeleteAgent401', DeleteAgent401), 403: ('DeleteAgent403', DeleteAgent403), 404: ('DeleteAgent404', DeleteAgent404), 409: ('DeleteAgent409', DeleteAgent409), 500: ('DeleteAgent500', DeleteAgent500), 503: ('DeleteAgent503', DeleteAgent503)})
_LIST_AGENT_ENVIRONMENT_TEMPLATES = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListAgentEnvironmentTemplates200, errors={400: ('ListAgentEnvironmentTemplates400', ListAgentEnvironmentTemplates400), 401: ('ListAgentEnvironmentTemplates401', ListAgentEnvironmentTemplates401), 403: ('ListAgentEnvironmentTemplates403', ListAgentEnvironmentTemplates403), 404: ('ListAgentEnvironmentTemplates404', ListAgentEnvironmentTemplates404), 500: ('ListAgentEnvironmentTemplates500', ListAgentEnvironmentTemplates500), 503: ('ListAgentEnvironmentTemplates503', ListAgentEnvironmentTemplates503)})
_CREATE_AGENT_ENVIRONMENT_TEMPLATE = _c.Operation("POST", success=CreateAgentEnvironmentTemplate201, errors={400: ('CreateAgentEnvironmentTemplate400', CreateAgentEnvironmentTemplate400), 401: ('CreateAgentEnvironmentTemplate401', CreateAgentEnvironmentTemplate401), 403: ('CreateAgentEnvironmentTemplate403', CreateAgentEnvironmentTemplate403), 404: ('CreateAgentEnvironmentTemplate404', CreateAgentEnvironmentTemplate404), 500: ('CreateAgentEnvironmentTemplate500', CreateAgentEnvironmentTemplate500), 503: ('CreateAgentEnvironmentTemplate503', CreateAgentEnvironmentTemplate503)})
_RETRIEVE_AGENT_ENVIRONMENT_TEMPLATE = _c.Operation("GET", success=RetrieveAgentEnvironmentTemplate200, errors={400: ('RetrieveAgentEnvironmentTemplate400', RetrieveAgentEnvironmentTemplate400), 401: ('RetrieveAgentEnvironmentTemplate401', RetrieveAgentEnvironmentTemplate401), 403: ('RetrieveAgentEnvironmentTemplate403', RetrieveAgentEnvironmentTemplate403), 404: ('RetrieveAgentEnvironmentTemplate404', RetrieveAgentEnvironmentTemplate404), 500: ('RetrieveAgentEnvironmentTemplate500', RetrieveAgentEnvironmentTemplate500), 503: ('RetrieveAgentEnvironmentTemplate503', RetrieveAgentEnvironmentTemplate503)})
_UPDATE_AGENT_ENVIRONMENT_TEMPLATE = _c.Operation("POST", success=UpdateAgentEnvironmentTemplate200, errors={400: ('UpdateAgentEnvironmentTemplate400', UpdateAgentEnvironmentTemplate400), 401: ('UpdateAgentEnvironmentTemplate401', UpdateAgentEnvironmentTemplate401), 403: ('UpdateAgentEnvironmentTemplate403', UpdateAgentEnvironmentTemplate403), 404: ('UpdateAgentEnvironmentTemplate404', UpdateAgentEnvironmentTemplate404), 409: ('UpdateAgentEnvironmentTemplate409', UpdateAgentEnvironmentTemplate409), 500: ('UpdateAgentEnvironmentTemplate500', UpdateAgentEnvironmentTemplate500), 503: ('UpdateAgentEnvironmentTemplate503', UpdateAgentEnvironmentTemplate503)})
_DELETE_AGENT_ENVIRONMENT_TEMPLATE = _c.Operation("DELETE", success=DeleteAgentEnvironmentTemplate200, errors={400: ('DeleteAgentEnvironmentTemplate400', DeleteAgentEnvironmentTemplate400), 401: ('DeleteAgentEnvironmentTemplate401', DeleteAgentEnvironmentTemplate401), 403: ('DeleteAgentEnvironmentTemplate403', DeleteAgentEnvironmentTemplate403), 404: ('DeleteAgentEnvironmentTemplate404', DeleteAgentEnvironmentTemplate404), 409: ('DeleteAgentEnvironmentTemplate409', DeleteAgentEnvironmentTemplate409), 500: ('DeleteAgentEnvironmentTemplate500', DeleteAgentEnvironmentTemplate500), 503: ('DeleteAgentEnvironmentTemplate503', DeleteAgentEnvironmentTemplate503)})
_LIST_AGENT_SESSIONS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'agent_id', ), success=ListAgentSessions200, errors={400: ('ListAgentSessions400', ListAgentSessions400), 401: ('ListAgentSessions401', ListAgentSessions401), 403: ('ListAgentSessions403', ListAgentSessions403), 404: ('ListAgentSessions404', ListAgentSessions404), 409: ('ListAgentSessions409', ListAgentSessions409), 500: ('ListAgentSessions500', ListAgentSessions500), 503: ('ListAgentSessions503', ListAgentSessions503)})
_CREATE_AGENT_SESSION = _c.Operation("POST", success=CreateAgentSession201, errors={400: ('CreateAgentSession400', CreateAgentSession400), 401: ('CreateAgentSession401', CreateAgentSession401), 403: ('CreateAgentSession403', CreateAgentSession403), 404: ('CreateAgentSession404', CreateAgentSession404), 409: ('CreateAgentSession409', CreateAgentSession409), 429: ('CreateAgentSession429', CreateAgentSession429), 500: ('CreateAgentSession500', CreateAgentSession500), 503: ('CreateAgentSession503', CreateAgentSession503)})
_CREATE_AGENT_SESSION_SSE = _c.Operation("POST")
_RETRIEVE_AGENT_SESSION = _c.Operation("GET", success=RetrieveAgentSession200, errors={400: ('RetrieveAgentSession400', RetrieveAgentSession400), 401: ('RetrieveAgentSession401', RetrieveAgentSession401), 403: ('RetrieveAgentSession403', RetrieveAgentSession403), 404: ('RetrieveAgentSession404', RetrieveAgentSession404), 409: ('RetrieveAgentSession409', RetrieveAgentSession409), 500: ('RetrieveAgentSession500', RetrieveAgentSession500), 503: ('RetrieveAgentSession503', RetrieveAgentSession503)})
_UPDATE_AGENT_SESSION = _c.Operation("POST", success=UpdateAgentSession200, errors={400: ('UpdateAgentSession400', UpdateAgentSession400), 401: ('UpdateAgentSession401', UpdateAgentSession401), 403: ('UpdateAgentSession403', UpdateAgentSession403), 404: ('UpdateAgentSession404', UpdateAgentSession404), 409: ('UpdateAgentSession409', UpdateAgentSession409), 500: ('UpdateAgentSession500', UpdateAgentSession500), 503: ('UpdateAgentSession503', UpdateAgentSession503)})
_DELETE_AGENT_SESSION = _c.Operation("DELETE", success=DeleteAgentSession200, errors={400: ('DeleteAgentSession400', DeleteAgentSession400), 401: ('DeleteAgentSession401', DeleteAgentSession401), 403: ('DeleteAgentSession403', DeleteAgentSession403), 404: ('DeleteAgentSession404', DeleteAgentSession404), 409: ('DeleteAgentSession409', DeleteAgentSession409), 500: ('DeleteAgentSession500', DeleteAgentSession500), 503: ('DeleteAgentSession503', DeleteAgentSession503)})
_LIST_AGENT_SESSION_ARTIFACTS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'environment_id', ), success=ListAgentSessionArtifacts200, errors={400: ('ListAgentSessionArtifacts400', ListAgentSessionArtifacts400), 401: ('ListAgentSessionArtifacts401', ListAgentSessionArtifacts401), 403: ('ListAgentSessionArtifacts403', ListAgentSessionArtifacts403), 404: ('ListAgentSessionArtifacts404', ListAgentSessionArtifacts404), 409: ('ListAgentSessionArtifacts409', ListAgentSessionArtifacts409), 500: ('ListAgentSessionArtifacts500', ListAgentSessionArtifacts500), 503: ('ListAgentSessionArtifacts503', ListAgentSessionArtifacts503)})
_RETRIEVE_AGENT_SESSION_ARTIFACT = _c.Operation("GET", success=RetrieveAgentSessionArtifact200, errors={400: ('RetrieveAgentSessionArtifact400', RetrieveAgentSessionArtifact400), 401: ('RetrieveAgentSessionArtifact401', RetrieveAgentSessionArtifact401), 403: ('RetrieveAgentSessionArtifact403', RetrieveAgentSessionArtifact403), 404: ('RetrieveAgentSessionArtifact404', RetrieveAgentSessionArtifact404), 409: ('RetrieveAgentSessionArtifact409', RetrieveAgentSessionArtifact409), 500: ('RetrieveAgentSessionArtifact500', RetrieveAgentSessionArtifact500), 503: ('RetrieveAgentSessionArtifact503', RetrieveAgentSessionArtifact503)})
_DELETE_AGENT_SESSION_ARTIFACT = _c.Operation("DELETE", success=DeleteAgentSessionArtifact200, errors={400: ('DeleteAgentSessionArtifact400', DeleteAgentSessionArtifact400), 401: ('DeleteAgentSessionArtifact401', DeleteAgentSessionArtifact401), 403: ('DeleteAgentSessionArtifact403', DeleteAgentSessionArtifact403), 404: ('DeleteAgentSessionArtifact404', DeleteAgentSessionArtifact404), 409: ('DeleteAgentSessionArtifact409', DeleteAgentSessionArtifact409), 500: ('DeleteAgentSessionArtifact500', DeleteAgentSessionArtifact500), 503: ('DeleteAgentSessionArtifact503', DeleteAgentSessionArtifact503)})
_RETRIEVE_AGENT_SESSION_ARTIFACT_CONTENT = _c.Operation("GET", binary_success=True, errors={400: ('RetrieveAgentSessionArtifactContent400', RetrieveAgentSessionArtifactContent400), 401: ('RetrieveAgentSessionArtifactContent401', RetrieveAgentSessionArtifactContent401), 403: ('RetrieveAgentSessionArtifactContent403', RetrieveAgentSessionArtifactContent403), 404: ('RetrieveAgentSessionArtifactContent404', RetrieveAgentSessionArtifactContent404), 409: ('RetrieveAgentSessionArtifactContent409', RetrieveAgentSessionArtifactContent409), 500: ('RetrieveAgentSessionArtifactContent500', RetrieveAgentSessionArtifactContent500), 503: ('RetrieveAgentSessionArtifactContent503', RetrieveAgentSessionArtifactContent503)})
_RETRIEVE_AGENT_SESSION_ARTIFACT_CONTENT_STREAM = _c.Operation("GET")
_LIST_AGENT_SESSION_EVENTS = _c.Operation("GET", errors={400: ('ListAgentSessionEvents400', ListAgentSessionEvents400), 401: ('ListAgentSessionEvents401', ListAgentSessionEvents401), 403: ('ListAgentSessionEvents403', ListAgentSessionEvents403), 404: ('ListAgentSessionEvents404', ListAgentSessionEvents404), 409: ('ListAgentSessionEvents409', ListAgentSessionEvents409), 500: ('ListAgentSessionEvents500', ListAgentSessionEvents500), 503: ('ListAgentSessionEvents503', ListAgentSessionEvents503)})
_LIST_AGENT_SESSION_EVENTS_SSE = _c.Operation("GET")
_CREATE_AGENT_SESSION_EVENTS = _c.Operation("POST", headers=('Idempotency-Key', ), void=(202, ), errors={400: ('CreateAgentSessionEvents400', CreateAgentSessionEvents400), 401: ('CreateAgentSessionEvents401', CreateAgentSessionEvents401), 403: ('CreateAgentSessionEvents403', CreateAgentSessionEvents403), 404: ('CreateAgentSessionEvents404', CreateAgentSessionEvents404), 409: ('CreateAgentSessionEvents409', CreateAgentSessionEvents409), 500: ('CreateAgentSessionEvents500', CreateAgentSessionEvents500), 503: ('CreateAgentSessionEvents503', CreateAgentSessionEvents503)})
_LIST_AGENT_SESSION_ITEMS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListAgentSessionItems200, errors={400: ('ListAgentSessionItems400', ListAgentSessionItems400), 401: ('ListAgentSessionItems401', ListAgentSessionItems401), 403: ('ListAgentSessionItems403', ListAgentSessionItems403), 404: ('ListAgentSessionItems404', ListAgentSessionItems404), 409: ('ListAgentSessionItems409', ListAgentSessionItems409), 500: ('ListAgentSessionItems500', ListAgentSessionItems500), 503: ('ListAgentSessionItems503', ListAgentSessionItems503)})
_LIST_AGENT_SESSION_TRACES = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListAgentSessionTraces200, errors={400: ('ListAgentSessionTraces400', ListAgentSessionTraces400), 401: ('ListAgentSessionTraces401', ListAgentSessionTraces401), 403: ('ListAgentSessionTraces403', ListAgentSessionTraces403), 404: ('ListAgentSessionTraces404', ListAgentSessionTraces404), 409: ('ListAgentSessionTraces409', ListAgentSessionTraces409), 500: ('ListAgentSessionTraces500', ListAgentSessionTraces500), 503: ('ListAgentSessionTraces503', ListAgentSessionTraces503)})
_LIST_AGENT_SESSION_TURNS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListAgentSessionTurns200, errors={400: ('ListAgentSessionTurns400', ListAgentSessionTurns400), 401: ('ListAgentSessionTurns401', ListAgentSessionTurns401), 403: ('ListAgentSessionTurns403', ListAgentSessionTurns403), 404: ('ListAgentSessionTurns404', ListAgentSessionTurns404), 409: ('ListAgentSessionTurns409', ListAgentSessionTurns409), 500: ('ListAgentSessionTurns500', ListAgentSessionTurns500), 503: ('ListAgentSessionTurns503', ListAgentSessionTurns503)})
_RETRIEVE_AGENT_SESSION_TURN = _c.Operation("GET", success=RetrieveAgentSessionTurn200, errors={400: ('RetrieveAgentSessionTurn400', RetrieveAgentSessionTurn400), 401: ('RetrieveAgentSessionTurn401', RetrieveAgentSessionTurn401), 403: ('RetrieveAgentSessionTurn403', RetrieveAgentSessionTurn403), 404: ('RetrieveAgentSessionTurn404', RetrieveAgentSessionTurn404), 409: ('RetrieveAgentSessionTurn409', RetrieveAgentSessionTurn409), 500: ('RetrieveAgentSessionTurn500', RetrieveAgentSessionTurn500), 503: ('RetrieveAgentSessionTurn503', RetrieveAgentSessionTurn503)})
_LIST_AGENT_SESSION_TURN_ITEMS = _c.Operation("GET", url_params=('limit', 'order', 'after', ), success=ListAgentSessionTurnItems200, errors={400: ('ListAgentSessionTurnItems400', ListAgentSessionTurnItems400), 401: ('ListAgentSessionTurnItems401', ListAgentSessionTurnItems401), 403: ('ListAgentSessionTurnItems403', ListAgentSessionTurnItems403), 404: ('ListAgentSessionTurnItems404', ListAgentSessionTurnItems404), 409: ('ListAgentSessionTurnItems409', ListAgentSessionTurnItems409), 500: ('ListAgentSessionTurnItems500', ListAgentSessionTurnItems500), 503: ('ListAgentSessionTurnItems503', ListAgentSessionTurnItems503)})
_LIST_VAULTS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'metadata', 'status', ), success=ListVaults200, errors={400: ('ListVaults400', ListVaults400), 401: ('ListVaults401', ListVaults401), 403: ('ListVaults403', ListVaults403), 404: ('ListVaults404', ListVaults404), 409: ('ListVaults409', ListVaults409), 500: ('ListVaults500', ListVaults500), 503: ('ListVaults503', ListVaults503)})
_CREATE_VAULT = _c.Operation("POST", success=CreateVault201, errors={400: ('CreateVault400', CreateVault400), 401: ('CreateVault401', CreateVault401), 403: ('CreateVault403', CreateVault403), 404: ('CreateVault404', CreateVault404), 409: ('CreateVault409', CreateVault409), 500: ('CreateVault500', CreateVault500), 503: ('CreateVault503', CreateVault503)})
_RETRIEVE_VAULT = _c.Operation("GET", success=RetrieveVault200, errors={400: ('RetrieveVault400', RetrieveVault400), 401: ('RetrieveVault401', RetrieveVault401), 403: ('RetrieveVault403', RetrieveVault403), 404: ('RetrieveVault404', RetrieveVault404), 409: ('RetrieveVault409', RetrieveVault409), 500: ('RetrieveVault500', RetrieveVault500), 503: ('RetrieveVault503', RetrieveVault503)})
_UPDATE_VAULT = _c.Operation("POST", success=UpdateVault200, errors={400: ('UpdateVault400', UpdateVault400), 401: ('UpdateVault401', UpdateVault401), 403: ('UpdateVault403', UpdateVault403), 404: ('UpdateVault404', UpdateVault404), 409: ('UpdateVault409', UpdateVault409), 500: ('UpdateVault500', UpdateVault500), 503: ('UpdateVault503', UpdateVault503)})
_DELETE_VAULT = _c.Operation("DELETE", success=DeleteVault200, errors={400: ('DeleteVault400', DeleteVault400), 401: ('DeleteVault401', DeleteVault401), 403: ('DeleteVault403', DeleteVault403), 404: ('DeleteVault404', DeleteVault404), 409: ('DeleteVault409', DeleteVault409), 500: ('DeleteVault500', DeleteVault500), 503: ('DeleteVault503', DeleteVault503)})
_LIST_VAULT_CREDENTIALS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'metadata', 'status', ), success=ListVaultCredentials200, errors={400: ('ListVaultCredentials400', ListVaultCredentials400), 401: ('ListVaultCredentials401', ListVaultCredentials401), 403: ('ListVaultCredentials403', ListVaultCredentials403), 404: ('ListVaultCredentials404', ListVaultCredentials404), 409: ('ListVaultCredentials409', ListVaultCredentials409), 500: ('ListVaultCredentials500', ListVaultCredentials500), 503: ('ListVaultCredentials503', ListVaultCredentials503)})
_CREATE_VAULT_CREDENTIAL = _c.Operation("POST", success=CreateVaultCredential201, errors={400: ('CreateVaultCredential400', CreateVaultCredential400), 401: ('CreateVaultCredential401', CreateVaultCredential401), 403: ('CreateVaultCredential403', CreateVaultCredential403), 404: ('CreateVaultCredential404', CreateVaultCredential404), 409: ('CreateVaultCredential409', CreateVaultCredential409), 500: ('CreateVaultCredential500', CreateVaultCredential500), 503: ('CreateVaultCredential503', CreateVaultCredential503)})
_RETRIEVE_VAULT_CREDENTIAL = _c.Operation("GET", success=RetrieveVaultCredential200, errors={400: ('RetrieveVaultCredential400', RetrieveVaultCredential400), 401: ('RetrieveVaultCredential401', RetrieveVaultCredential401), 403: ('RetrieveVaultCredential403', RetrieveVaultCredential403), 404: ('RetrieveVaultCredential404', RetrieveVaultCredential404), 409: ('RetrieveVaultCredential409', RetrieveVaultCredential409), 500: ('RetrieveVaultCredential500', RetrieveVaultCredential500), 503: ('RetrieveVaultCredential503', RetrieveVaultCredential503)})
_ROTATE_VAULT_CREDENTIAL = _c.Operation("POST", success=RotateVaultCredential200, errors={400: ('RotateVaultCredential400', RotateVaultCredential400), 401: ('RotateVaultCredential401', RotateVaultCredential401), 403: ('RotateVaultCredential403', RotateVaultCredential403), 404: ('RotateVaultCredential404', RotateVaultCredential404), 409: ('RotateVaultCredential409', RotateVaultCredential409), 500: ('RotateVaultCredential500', RotateVaultCredential500), 503: ('RotateVaultCredential503', RotateVaultCredential503)})
_DELETE_VAULT_CREDENTIAL = _c.Operation("DELETE", success=DeleteVaultCredential200, errors={400: ('DeleteVaultCredential400', DeleteVaultCredential400), 401: ('DeleteVaultCredential401', DeleteVaultCredential401), 403: ('DeleteVaultCredential403', DeleteVaultCredential403), 404: ('DeleteVaultCredential404', DeleteVaultCredential404), 409: ('DeleteVaultCredential409', DeleteVaultCredential409), 500: ('DeleteVaultCredential500', DeleteVaultCredential500), 503: ('DeleteVaultCredential503', DeleteVaultCredential503)})
_LIST_WEBHOOK_ENDPOINTS = _c.Operation("GET", url_params=('limit', 'after', ), success=ListWebhookEndpoints200, errors={400: ('ListWebhookEndpoints400', ListWebhookEndpoints400), 404: ('ListWebhookEndpoints404', ListWebhookEndpoints404)})
_CREATE_WEBHOOK_ENDPOINT = _c.Operation("POST", success=CreateWebhookEndpoint200, errors={400: ('CreateWebhookEndpoint400', CreateWebhookEndpoint400)})
_RETRIEVE_WEBHOOK_ENDPOINT = _c.Operation("GET", success=RetrieveWebhookEndpoint200, errors={400: ('RetrieveWebhookEndpoint400', RetrieveWebhookEndpoint400), 404: ('RetrieveWebhookEndpoint404', RetrieveWebhookEndpoint404)})
_UPDATE_WEBHOOK_ENDPOINT = _c.Operation("POST", success=UpdateWebhookEndpoint200, errors={400: ('UpdateWebhookEndpoint400', UpdateWebhookEndpoint400), 404: ('UpdateWebhookEndpoint404', UpdateWebhookEndpoint404)})
_DELETE_WEBHOOK_ENDPOINT = _c.Operation("DELETE", success=DeleteWebhookEndpoint200, errors={400: ('DeleteWebhookEndpoint400', DeleteWebhookEndpoint400), 404: ('DeleteWebhookEndpoint404', DeleteWebhookEndpoint404)})
_ROTATE_WEBHOOK_ENDPOINT_SIGNING_SECRET = _c.Operation("POST", success=RotateWebhookEndpointSigningSecret200, errors={400: ('RotateWebhookEndpointSigningSecret400', RotateWebhookEndpointSigningSecret400), 404: ('RotateWebhookEndpointSigningSecret404', RotateWebhookEndpointSigningSecret404)})
_TEST_WEBHOOK_ENDPOINT = _c.Operation("POST", success=TestWebhookEndpoint200, errors={400: ('TestWebhookEndpoint400', TestWebhookEndpoint400), 404: ('TestWebhookEndpoint404', TestWebhookEndpoint404), 500: ('TestWebhookEndpoint500', TestWebhookEndpoint500)})
_LIST_WEBHOOK_EVENT_TYPES = _c.Operation("GET", success=ListWebhookEventTypes200, errors={401: ('ListWebhookEventTypes401', ListWebhookEventTypes401)})
_BETA_CREATE_RESPONSE = _c.Operation("POST", headers=('openai-beta', ), success=BetaCreateResponse200, errors={400: ('BetaCreateResponse400', BetaCreateResponse400), 404: ('BetaCreateResponse404', BetaCreateResponse404), 429: ('BetaCreateResponse429', BetaCreateResponse429), 503: ('BetaCreateResponse503', BetaCreateResponse503)})
_BETA_CREATE_RESPONSE_SSE = _c.Operation("POST", headers=('openai-beta', ))
_BETA_GET_RESPONSE = _c.Operation("GET", url_params=('include', 'stream', 'starting_after', 'include_obfuscation', ), headers=('openai-beta', ), success=BetaGetResponse200, errors={404: ('BetaGetResponse404', BetaGetResponse404), 429: ('BetaGetResponse429', BetaGetResponse429)})
_BETA_DELETE_RESPONSE = _c.Operation("DELETE", headers=('openai-beta', ), success=BetaDeleteResponse200, errors={404: ('BetaDeleteResponse404', BetaDeleteResponse404), 429: ('BetaDeleteResponse429', BetaDeleteResponse429)})
_BETA_CANCEL_RESPONSE = _c.Operation("POST", headers=('openai-beta', ), success=BetaCancelResponse200, errors={404: ('BetaCancelResponse404', BetaCancelResponse404), 429: ('BetaCancelResponse429', BetaCancelResponse429)})
_BETA_COMPACTCONVERSATION = _c.Operation("POST", headers=('openai-beta', ), success=BetaCompactconversation200, errors={400: ('BetaCompactconversation400', BetaCompactconversation400), 429: ('BetaCompactconversation429', BetaCompactconversation429), 503: ('BetaCompactconversation503', BetaCompactconversation503)})
_BETA_LIST_INPUT_ITEMS = _c.Operation("GET", url_params=('limit', 'order', 'after', 'include', ), headers=('openai-beta', ), success=BetaListInputItems200, errors={404: ('BetaListInputItems404', BetaListInputItems404), 429: ('BetaListInputItems429', BetaListInputItems429)})
_BETA_GETINPUTTOKENCOUNTS = _c.Operation("POST", headers=('openai-beta', ), success=BetaGetinputtokencounts200, errors={400: ('BetaGetinputtokencounts400', BetaGetinputtokencounts400), 429: ('BetaGetinputtokencounts429', BetaGetinputtokencounts429)})


class OpenAiClient(_c.GeneratedClient):
    """The OpenAI API: build it with ``make``."""

    __slots__ = ()

    error_class = OpenAiClientError
    transform_streams = True

    @_t.overload
    def list_assistants(self, *, params: _T.ListAssistantsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAssistants200, _Errors]: ...
    @_t.overload
    def list_assistants(self, *, params: _T.ListAssistantsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAssistants200, _HttpClientResponse], _Errors]: ...
    def list_assistants(self, *, params: _T.ListAssistantsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of assistants."""
        return self._json(_LIST_ASSISTANTS, "/assistants", params, None, include_response)

    @_t.overload
    def create_assistant(self, *, payload: _T.CreateAssistantRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateAssistant200, _Errors]: ...
    @_t.overload
    def create_assistant(self, *, payload: _T.CreateAssistantRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateAssistant200, _HttpClientResponse], _Errors]: ...
    def create_assistant(self, *, payload: _T.CreateAssistantRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create an assistant with a model and instructions."""
        return self._json(_CREATE_ASSISTANT, "/assistants", None, _c.json_body(payload), include_response)

    @_t.overload
    def get_assistant(self, assistant_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetAssistant200, _Errors]: ...
    @_t.overload
    def get_assistant(self, assistant_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetAssistant200, _HttpClientResponse], _Errors]: ...
    def get_assistant(self, assistant_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves an assistant."""
        return self._json(_GET_ASSISTANT, _c.encoded_path("/assistants/{}", assistant_id), None, None, include_response)

    @_t.overload
    def modify_assistant(self, assistant_id: str, *, payload: _T.ModifyAssistantRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ModifyAssistant200, _Errors]: ...
    @_t.overload
    def modify_assistant(self, assistant_id: str, *, payload: _T.ModifyAssistantRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ModifyAssistant200, _HttpClientResponse], _Errors]: ...
    def modify_assistant(self, assistant_id: str, *, payload: _T.ModifyAssistantRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Modifies an assistant."""
        return self._json(_MODIFY_ASSISTANT, _c.encoded_path("/assistants/{}", assistant_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_assistant(self, assistant_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteAssistant200, _Errors]: ...
    @_t.overload
    def delete_assistant(self, assistant_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteAssistant200, _HttpClientResponse], _Errors]: ...
    def delete_assistant(self, assistant_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an assistant."""
        return self._json(_DELETE_ASSISTANT, _c.encoded_path("/assistants/{}", assistant_id), None, None, include_response)

    @_t.overload
    def create_speech(self, *, payload: _T.CreateSpeechRequestJson, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def create_speech(self, *, payload: _T.CreateSpeechRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def create_speech(self, *, payload: _T.CreateSpeechRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Generates audio from the input text.
        
        Returns the audio file content, or a stream of audio events."""
        return self._json(_CREATE_SPEECH, "/audio/speech", None, _c.json_body(payload), include_response)

    def create_speech_sse(self, *, payload: _T.CreateSpeechRequestJson) -> _Stream[_sse.DataEvent[_T.CreateSpeech200Sse], _SseErrors]:
        """Generates audio from the input text.
        
        Returns the audio file content, or a stream of audio events."""
        return self._sse(_CREATE_SPEECH_SSE, "/audio/speech", None, _c.json_body(payload), CreateSpeech200Sse)

    def create_speech_stream(self, *, payload: _T.CreateSpeechRequestJson) -> _Stream[bytes, _HttpClientError]:
        """Generates audio from the input text.
        
        Returns the audio file content, or a stream of audio events."""
        return self._binary(_CREATE_SPEECH_STREAM, "/audio/speech", None, _c.json_body(payload))

    @_t.overload
    def create_transcription(self, *, payload: _T.CreateTranscriptionRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateTranscription200, _Errors]: ...
    @_t.overload
    def create_transcription(self, *, payload: _T.CreateTranscriptionRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateTranscription200, _HttpClientResponse], _Errors]: ...
    def create_transcription(self, *, payload: _T.CreateTranscriptionRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Transcribes audio into the input language.
        
        Returns a transcription object in `json`, `diarized_json`, or `verbose_json`
        format, plain text in `text`, `srt`, or `vtt` format, or a stream of
        transcript events. Supported formats depend on the model."""
        return self._json(_CREATE_TRANSCRIPTION, "/audio/transcriptions", None, _c.form_body(payload), include_response)

    def create_transcription_sse(self, *, payload: _T.CreateTranscriptionRequestFormData) -> _Stream[_sse.DataEvent[_T.CreateTranscription200Sse], _SseErrors]:
        """Transcribes audio into the input language.
        
        Returns a transcription object in `json`, `diarized_json`, or `verbose_json`
        format, plain text in `text`, `srt`, or `vtt` format, or a stream of
        transcript events. Supported formats depend on the model."""
        return self._sse(_CREATE_TRANSCRIPTION_SSE, "/audio/transcriptions", None, _c.form_body(payload), CreateTranscription200Sse)

    @_t.overload
    def create_translation(self, *, payload: _T.CreateTranslationRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateTranslation200, _Errors]: ...
    @_t.overload
    def create_translation(self, *, payload: _T.CreateTranslationRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateTranslation200, _HttpClientResponse], _Errors]: ...
    def create_translation(self, *, payload: _T.CreateTranslationRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Translates audio into English."""
        return self._json(_CREATE_TRANSLATION, "/audio/translations", None, _c.form_body(payload), include_response)

    @_t.overload
    def list_voice_consents(self, *, params: _T.ListVoiceConsentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListVoiceConsents200, _Errors]: ...
    @_t.overload
    def list_voice_consents(self, *, params: _T.ListVoiceConsentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListVoiceConsents200, _HttpClientResponse], _Errors]: ...
    def list_voice_consents(self, *, params: _T.ListVoiceConsentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of voice consent recordings."""
        return self._json(_LIST_VOICE_CONSENTS, "/audio/voice_consents", params, None, include_response)

    @_t.overload
    def create_voice_consent(self, *, payload: _T.CreateVoiceConsentRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVoiceConsent200, _Errors]: ...
    @_t.overload
    def create_voice_consent(self, *, payload: _T.CreateVoiceConsentRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVoiceConsent200, _HttpClientResponse], _Errors]: ...
    def create_voice_consent(self, *, payload: _T.CreateVoiceConsentRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Upload a voice consent recording."""
        return self._json(_CREATE_VOICE_CONSENT, "/audio/voice_consents", None, _c.form_body(payload), include_response)

    @_t.overload
    def get_voice_consent(self, consent_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetVoiceConsent200, _Errors]: ...
    @_t.overload
    def get_voice_consent(self, consent_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetVoiceConsent200, _HttpClientResponse], _Errors]: ...
    def get_voice_consent(self, consent_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a voice consent recording."""
        return self._json(_GET_VOICE_CONSENT, _c.encoded_path("/audio/voice_consents/{}", consent_id), None, None, include_response)

    @_t.overload
    def update_voice_consent(self, consent_id: str, *, payload: _T.UpdateVoiceConsentRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateVoiceConsent200, _Errors]: ...
    @_t.overload
    def update_voice_consent(self, consent_id: str, *, payload: _T.UpdateVoiceConsentRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateVoiceConsent200, _HttpClientResponse], _Errors]: ...
    def update_voice_consent(self, consent_id: str, *, payload: _T.UpdateVoiceConsentRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates a voice consent recording (metadata only)."""
        return self._json(_UPDATE_VOICE_CONSENT, _c.encoded_path("/audio/voice_consents/{}", consent_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_voice_consent(self, consent_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteVoiceConsent200, _Errors]: ...
    @_t.overload
    def delete_voice_consent(self, consent_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteVoiceConsent200, _HttpClientResponse], _Errors]: ...
    def delete_voice_consent(self, consent_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a voice consent recording."""
        return self._json(_DELETE_VOICE_CONSENT, _c.encoded_path("/audio/voice_consents/{}", consent_id), None, None, include_response)

    @_t.overload
    def create_voice(self, *, payload: _T.CreateVoiceRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVoice200, _Errors]: ...
    @_t.overload
    def create_voice(self, *, payload: _T.CreateVoiceRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVoice200, _HttpClientResponse], _Errors]: ...
    def create_voice(self, *, payload: _T.CreateVoiceRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a custom voice you can use for audio output (for example, in Text-to-Speech and the Realtime API). This requires an audio sample and a previously uploaded consent recording.
        
        Send `name`, `audio_sample`, and the `consent` recording ID as multipart form data. The optional `type` defaults to `audio_sample`.
        
        Returns the saved voice's metadata. See the [custom voices guide](https://developers.openai.com/api/docs/guides/text-to-speech#custom-voices) for requirements and best practices. Custom voices are limited to eligible customers."""
        return self._json(_CREATE_VOICE, "/audio/voices", None, _c.form_body(payload), include_response)

    @_t.overload
    def list_batches(self, *, params: _T.ListBatchesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListBatches200, _Errors]: ...
    @_t.overload
    def list_batches(self, *, params: _T.ListBatchesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListBatches200, _HttpClientResponse], _Errors]: ...
    def list_batches(self, *, params: _T.ListBatchesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List your organization's batches."""
        return self._json(_LIST_BATCHES, "/batches", params, None, include_response)

    @_t.overload
    def create_batch(self, *, payload: _T.CreateBatchRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateBatch200, _Errors]: ...
    @_t.overload
    def create_batch(self, *, payload: _T.CreateBatchRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateBatch200, _HttpClientResponse], _Errors]: ...
    def create_batch(self, *, payload: _T.CreateBatchRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates and executes a batch from an uploaded file of requests"""
        return self._json(_CREATE_BATCH, "/batches", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_batch(self, batch_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveBatch200, _Errors]: ...
    @_t.overload
    def retrieve_batch(self, batch_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveBatch200, _HttpClientResponse], _Errors]: ...
    def retrieve_batch(self, batch_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a batch."""
        return self._json(_RETRIEVE_BATCH, _c.encoded_path("/batches/{}", batch_id), None, None, include_response)

    @_t.overload
    def cancel_batch(self, batch_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.CancelBatch200, _Errors]: ...
    @_t.overload
    def cancel_batch(self, batch_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CancelBatch200, _HttpClientResponse], _Errors]: ...
    def cancel_batch(self, batch_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Cancels an in-progress batch. The batch will be in status `cancelling` for up to 10 minutes, before changing to `cancelled`, where it will have partial results (if any) available in the output file."""
        return self._json(_CANCEL_BATCH, _c.encoded_path("/batches/{}/cancel", batch_id), None, None, include_response)

    @_t.overload
    def list_chat_completions(self, *, params: _T.ListChatCompletionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListChatCompletions200, _Errors]: ...
    @_t.overload
    def list_chat_completions(self, *, params: _T.ListChatCompletionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListChatCompletions200, _HttpClientResponse], _Errors]: ...
    def list_chat_completions(self, *, params: _T.ListChatCompletionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List stored Chat Completions. Only Chat Completions that have been stored
        with the `store` parameter set to `true` will be returned."""
        return self._json(_LIST_CHAT_COMPLETIONS, "/chat/completions", params, None, include_response)

    @_t.overload
    def create_chat_completion(self, *, payload: _T.CreateChatCompletionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateChatCompletion200, _Errors]: ...
    @_t.overload
    def create_chat_completion(self, *, payload: _T.CreateChatCompletionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateChatCompletion200, _HttpClientResponse], _Errors]: ...
    def create_chat_completion(self, *, payload: _T.CreateChatCompletionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """**Starting a new project?** We recommend trying [Responses](https://developers.openai.com/api/reference/resources/responses)
        to take advantage of the latest OpenAI platform features. Compare
        [Chat Completions with Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses?api-mode=responses).
        
        ---
        
        Creates a model response for the given chat conversation. Learn more in the
        [text generation](https://developers.openai.com/api/docs/guides/text), [vision](https://developers.openai.com/api/docs/guides/images-vision),
        and [audio](https://developers.openai.com/api/docs/guides/audio) guides.
        
        Parameter support can differ depending on the model used to generate the
        response, particularly for newer reasoning models. Parameters that are only
        supported for reasoning models are noted below. For the current state of
        unsupported parameters in reasoning models,
        [refer to the reasoning guide](https://developers.openai.com/api/docs/guides/reasoning).
        
        Returns a chat completion object, or a streamed sequence of chat completion
        chunk objects if the request is streamed."""
        return self._json(_CREATE_CHAT_COMPLETION, "/chat/completions", None, _c.json_body(payload), include_response)

    def create_chat_completion_sse(self, *, payload: _T.CreateChatCompletionRequestJson) -> _Stream[_sse.DataEvent[_T.CreateChatCompletion200Sse], _SseErrors]:
        """**Starting a new project?** We recommend trying [Responses](https://developers.openai.com/api/reference/resources/responses)
        to take advantage of the latest OpenAI platform features. Compare
        [Chat Completions with Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses?api-mode=responses).
        
        ---
        
        Creates a model response for the given chat conversation. Learn more in the
        [text generation](https://developers.openai.com/api/docs/guides/text), [vision](https://developers.openai.com/api/docs/guides/images-vision),
        and [audio](https://developers.openai.com/api/docs/guides/audio) guides.
        
        Parameter support can differ depending on the model used to generate the
        response, particularly for newer reasoning models. Parameters that are only
        supported for reasoning models are noted below. For the current state of
        unsupported parameters in reasoning models,
        [refer to the reasoning guide](https://developers.openai.com/api/docs/guides/reasoning).
        
        Returns a chat completion object, or a streamed sequence of chat completion
        chunk objects if the request is streamed."""
        return self._sse(_CREATE_CHAT_COMPLETION_SSE, "/chat/completions", None, _c.json_body(payload), CreateChatCompletion200Sse)

    @_t.overload
    def get_chat_completion(self, completion_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetChatCompletion200, _Errors]: ...
    @_t.overload
    def get_chat_completion(self, completion_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetChatCompletion200, _HttpClientResponse], _Errors]: ...
    def get_chat_completion(self, completion_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a stored chat completion. Only Chat Completions that have been created
        with the `store` parameter set to `true` will be returned."""
        return self._json(_GET_CHAT_COMPLETION, _c.encoded_path("/chat/completions/{}", completion_id), None, None, include_response)

    @_t.overload
    def update_chat_completion(self, completion_id: str, *, payload: _T.UpdateChatCompletionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateChatCompletion200, _Errors]: ...
    @_t.overload
    def update_chat_completion(self, completion_id: str, *, payload: _T.UpdateChatCompletionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateChatCompletion200, _HttpClientResponse], _Errors]: ...
    def update_chat_completion(self, completion_id: str, *, payload: _T.UpdateChatCompletionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Modify a stored chat completion. Only Chat Completions that have been
        created with the `store` parameter set to `true` can be modified. Currently,
        the only supported modification is to update the `metadata` field."""
        return self._json(_UPDATE_CHAT_COMPLETION, _c.encoded_path("/chat/completions/{}", completion_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_chat_completion(self, completion_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteChatCompletion200, _Errors]: ...
    @_t.overload
    def delete_chat_completion(self, completion_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteChatCompletion200, _HttpClientResponse], _Errors]: ...
    def delete_chat_completion(self, completion_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a stored chat completion. Only Chat Completions that have been
        created with the `store` parameter set to `true` can be deleted."""
        return self._json(_DELETE_CHAT_COMPLETION, _c.encoded_path("/chat/completions/{}", completion_id), None, None, include_response)

    @_t.overload
    def get_chat_completion_messages(self, completion_id: str, *, params: _T.GetChatCompletionMessagesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetChatCompletionMessages200, _Errors]: ...
    @_t.overload
    def get_chat_completion_messages(self, completion_id: str, *, params: _T.GetChatCompletionMessagesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetChatCompletionMessages200, _HttpClientResponse], _Errors]: ...
    def get_chat_completion_messages(self, completion_id: str, *, params: _T.GetChatCompletionMessagesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get the messages in a stored chat completion. Only Chat Completions that
        have been created with the `store` parameter set to `true` will be
        returned."""
        return self._json(_GET_CHAT_COMPLETION_MESSAGES, _c.encoded_path("/chat/completions/{}/messages", completion_id), params, None, include_response)

    @_t.overload
    def create_completion(self, *, payload: _T.CreateCompletionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateCompletion200, _Errors]: ...
    @_t.overload
    def create_completion(self, *, payload: _T.CreateCompletionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateCompletion200, _HttpClientResponse], _Errors]: ...
    def create_completion(self, *, payload: _T.CreateCompletionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a completion for the provided prompt and parameters.
        
        Returns a completion object, or a sequence of completion objects if the request is streamed."""
        return self._json(_CREATE_COMPLETION, "/completions", None, _c.json_body(payload), include_response)

    @_t.overload
    def list_containers(self, *, params: _T.ListContainersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListContainers200, _Errors]: ...
    @_t.overload
    def list_containers(self, *, params: _T.ListContainersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListContainers200, _HttpClientResponse], _Errors]: ...
    def list_containers(self, *, params: _T.ListContainersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List Containers"""
        return self._json(_LIST_CONTAINERS, "/containers", params, None, include_response)

    @_t.overload
    def create_container(self, *, payload: _T.CreateContainerRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateContainer200, _Errors]: ...
    @_t.overload
    def create_container(self, *, payload: _T.CreateContainerRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateContainer200, _HttpClientResponse], _Errors]: ...
    def create_container(self, *, payload: _T.CreateContainerRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create Container"""
        return self._json(_CREATE_CONTAINER, "/containers", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_container(self, container_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveContainer200, _Errors]: ...
    @_t.overload
    def retrieve_container(self, container_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveContainer200, _HttpClientResponse], _Errors]: ...
    def retrieve_container(self, container_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieve Container"""
        return self._json(_RETRIEVE_CONTAINER, _c.encoded_path("/containers/{}", container_id), None, None, include_response)

    @_t.overload
    def delete_container(self, container_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteContainer200, _Errors]: ...
    @_t.overload
    def delete_container(self, container_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteContainer200, _HttpClientResponse], _Errors]: ...
    def delete_container(self, container_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete Container"""
        return self._json(_DELETE_CONTAINER, _c.encoded_path("/containers/{}", container_id), None, None, include_response)

    @_t.overload
    def list_container_files(self, container_id: str, *, params: _T.ListContainerFilesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListContainerFiles200, _Errors]: ...
    @_t.overload
    def list_container_files(self, container_id: str, *, params: _T.ListContainerFilesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListContainerFiles200, _HttpClientResponse], _Errors]: ...
    def list_container_files(self, container_id: str, *, params: _T.ListContainerFilesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List Container files"""
        return self._json(_LIST_CONTAINER_FILES, _c.encoded_path("/containers/{}/files", container_id), params, None, include_response)

    @_t.overload
    def create_container_file(self, container_id: str, *, payload: _T.CreateContainerFileRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateContainerFile200, _Errors]: ...
    @_t.overload
    def create_container_file(self, container_id: str, *, payload: _T.CreateContainerFileRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateContainerFile200, _HttpClientResponse], _Errors]: ...
    def create_container_file(self, container_id: str, *, payload: _T.CreateContainerFileRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a Container File
        
        You can send either a multipart/form-data request with the raw file content, or a JSON request with a file ID."""
        return self._json(_CREATE_CONTAINER_FILE, _c.encoded_path("/containers/{}/files", container_id), None, _c.form_body(payload), include_response)

    @_t.overload
    def retrieve_container_file(self, container_id: str, file_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveContainerFile200, _Errors]: ...
    @_t.overload
    def retrieve_container_file(self, container_id: str, file_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveContainerFile200, _HttpClientResponse], _Errors]: ...
    def retrieve_container_file(self, container_id: str, file_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieve Container File"""
        return self._json(_RETRIEVE_CONTAINER_FILE, _c.encoded_path("/containers/{}/files/{}", container_id, file_id), None, None, include_response)

    @_t.overload
    def delete_container_file(self, container_id: str, file_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteContainerFile200, _Errors]: ...
    @_t.overload
    def delete_container_file(self, container_id: str, file_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteContainerFile200, _HttpClientResponse], _Errors]: ...
    def delete_container_file(self, container_id: str, file_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete Container File"""
        return self._json(_DELETE_CONTAINER_FILE, _c.encoded_path("/containers/{}/files/{}", container_id, file_id), None, None, include_response)

    @_t.overload
    def retrieve_container_file_content(self, container_id: str, file_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def retrieve_container_file_content(self, container_id: str, file_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def retrieve_container_file_content(self, container_id: str, file_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieve Container File Content"""
        return self._json(_RETRIEVE_CONTAINER_FILE_CONTENT, _c.encoded_path("/containers/{}/files/{}/content", container_id, file_id), None, None, include_response)

    def retrieve_container_file_content_stream(self, container_id: str, file_id: str) -> _Stream[bytes, _HttpClientError]:
        """Retrieve Container File Content"""
        return self._binary(_RETRIEVE_CONTAINER_FILE_CONTENT_STREAM, _c.encoded_path("/containers/{}/files/{}/content", container_id, file_id), None, None)

    @_t.overload
    def list_conversation_items(self, conversation_id: str, *, params: _T.ListConversationItemsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListConversationItems200, _Errors]: ...
    @_t.overload
    def list_conversation_items(self, conversation_id: str, *, params: _T.ListConversationItemsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListConversationItems200, _HttpClientResponse], _Errors]: ...
    def list_conversation_items(self, conversation_id: str, *, params: _T.ListConversationItemsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all items for a conversation with the given ID."""
        return self._json(_LIST_CONVERSATION_ITEMS, _c.encoded_path("/conversations/{}/items", conversation_id), params, None, include_response)

    @_t.overload
    def create_conversation_items(self, conversation_id: str, *, payload: _T.CreateConversationItemsRequestJson, params: _T.CreateConversationItemsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateConversationItems200, _Errors]: ...
    @_t.overload
    def create_conversation_items(self, conversation_id: str, *, payload: _T.CreateConversationItemsRequestJson, params: _T.CreateConversationItemsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateConversationItems200, _HttpClientResponse], _Errors]: ...
    def create_conversation_items(self, conversation_id: str, *, payload: _T.CreateConversationItemsRequestJson, params: _T.CreateConversationItemsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create items in a conversation with the given ID."""
        return self._json(_CREATE_CONVERSATION_ITEMS, _c.encoded_path("/conversations/{}/items", conversation_id), params, _c.json_body(payload), include_response)

    @_t.overload
    def get_conversation_item(self, conversation_id: str, item_id: str, *, params: _T.GetConversationItemParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetConversationItem200, _Errors]: ...
    @_t.overload
    def get_conversation_item(self, conversation_id: str, item_id: str, *, params: _T.GetConversationItemParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetConversationItem200, _HttpClientResponse], _Errors]: ...
    def get_conversation_item(self, conversation_id: str, item_id: str, *, params: _T.GetConversationItemParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a single item from a conversation with the given IDs."""
        return self._json(_GET_CONVERSATION_ITEM, _c.encoded_path("/conversations/{}/items/{}", conversation_id, item_id), params, None, include_response)

    @_t.overload
    def delete_conversation_item(self, conversation_id: str, item_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteConversationItem200, _Errors]: ...
    @_t.overload
    def delete_conversation_item(self, conversation_id: str, item_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteConversationItem200, _HttpClientResponse], _Errors]: ...
    def delete_conversation_item(self, conversation_id: str, item_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an item from a conversation with the given IDs."""
        return self._json(_DELETE_CONVERSATION_ITEM, _c.encoded_path("/conversations/{}/items/{}", conversation_id, item_id), None, None, include_response)

    @_t.overload
    def create_embedding(self, *, payload: _T.CreateEmbeddingRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateEmbedding200, _Errors]: ...
    @_t.overload
    def create_embedding(self, *, payload: _T.CreateEmbeddingRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateEmbedding200, _HttpClientResponse], _Errors]: ...
    def create_embedding(self, *, payload: _T.CreateEmbeddingRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates an embedding vector representing the input text."""
        return self._json(_CREATE_EMBEDDING, "/embeddings", None, _c.json_body(payload), include_response)

    @_t.overload
    def list_evals(self, *, params: _T.ListEvalsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListEvals200, _Errors]: ...
    @_t.overload
    def list_evals(self, *, params: _T.ListEvalsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListEvals200, _HttpClientResponse], _Errors]: ...
    def list_evals(self, *, params: _T.ListEvalsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List evaluations for a project."""
        return self._json(_LIST_EVALS, "/evals", params, None, include_response)

    @_t.overload
    def create_eval(self, *, payload: _T.CreateEvalRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateEval201, _Errors]: ...
    @_t.overload
    def create_eval(self, *, payload: _T.CreateEvalRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateEval201, _HttpClientResponse], _Errors]: ...
    def create_eval(self, *, payload: _T.CreateEvalRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create the structure of an evaluation that can be used to test a model's performance.
        An evaluation is a set of testing criteria and the config for a data source, which dictates the schema of the data used in the evaluation. After creating an evaluation, you can run it on different models and model parameters. We support several types of graders and datasources.
        For more information, see the [Evals guide](https://developers.openai.com/api/docs/guides/evals)."""
        return self._json(_CREATE_EVAL, "/evals", None, _c.json_body(payload), include_response)

    @_t.overload
    def get_eval(self, eval_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetEval200, _Errors]: ...
    @_t.overload
    def get_eval(self, eval_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetEval200, _HttpClientResponse], _Errors]: ...
    def get_eval(self, eval_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get an evaluation by ID."""
        return self._json(_GET_EVAL, _c.encoded_path("/evals/{}", eval_id), None, None, include_response)

    @_t.overload
    def update_eval(self, eval_id: str, *, payload: _T.UpdateEvalRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateEval200, _Errors]: ...
    @_t.overload
    def update_eval(self, eval_id: str, *, payload: _T.UpdateEvalRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateEval200, _HttpClientResponse], _Errors]: ...
    def update_eval(self, eval_id: str, *, payload: _T.UpdateEvalRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update certain properties of an evaluation."""
        return self._json(_UPDATE_EVAL, _c.encoded_path("/evals/{}", eval_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_eval(self, eval_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteEval200, _Errors]: ...
    @_t.overload
    def delete_eval(self, eval_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteEval200, _HttpClientResponse], _Errors]: ...
    def delete_eval(self, eval_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an evaluation."""
        return self._json(_DELETE_EVAL, _c.encoded_path("/evals/{}", eval_id), None, None, include_response)

    @_t.overload
    def get_eval_runs(self, eval_id: str, *, params: _T.GetEvalRunsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetEvalRuns200, _Errors]: ...
    @_t.overload
    def get_eval_runs(self, eval_id: str, *, params: _T.GetEvalRunsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetEvalRuns200, _HttpClientResponse], _Errors]: ...
    def get_eval_runs(self, eval_id: str, *, params: _T.GetEvalRunsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a list of runs for an evaluation."""
        return self._json(_GET_EVAL_RUNS, _c.encoded_path("/evals/{}/runs", eval_id), params, None, include_response)

    @_t.overload
    def create_eval_run(self, eval_id: str, *, payload: _T.CreateEvalRunRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateEvalRun201, _Errors]: ...
    @_t.overload
    def create_eval_run(self, eval_id: str, *, payload: _T.CreateEvalRunRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateEvalRun201, _HttpClientResponse], _Errors]: ...
    def create_eval_run(self, eval_id: str, *, payload: _T.CreateEvalRunRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Kicks off a new run for a given evaluation, specifying the data source, and what model configuration to use to test. The datasource will be validated against the schema specified in the config of the evaluation."""
        return self._json(_CREATE_EVAL_RUN, _c.encoded_path("/evals/{}/runs", eval_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def get_eval_run(self, eval_id: str, run_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetEvalRun200, _Errors]: ...
    @_t.overload
    def get_eval_run(self, eval_id: str, run_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetEvalRun200, _HttpClientResponse], _Errors]: ...
    def get_eval_run(self, eval_id: str, run_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get an evaluation run by ID."""
        return self._json(_GET_EVAL_RUN, _c.encoded_path("/evals/{}/runs/{}", eval_id, run_id), None, None, include_response)

    @_t.overload
    def delete_eval_run(self, eval_id: str, run_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteEvalRun200, _Errors]: ...
    @_t.overload
    def delete_eval_run(self, eval_id: str, run_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteEvalRun200, _HttpClientResponse], _Errors]: ...
    def delete_eval_run(self, eval_id: str, run_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an eval run."""
        return self._json(_DELETE_EVAL_RUN, _c.encoded_path("/evals/{}/runs/{}", eval_id, run_id), None, None, include_response)

    @_t.overload
    def cancel_eval_run(self, eval_id: str, run_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.CancelEvalRun200, _Errors]: ...
    @_t.overload
    def cancel_eval_run(self, eval_id: str, run_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CancelEvalRun200, _HttpClientResponse], _Errors]: ...
    def cancel_eval_run(self, eval_id: str, run_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Cancel an ongoing evaluation run."""
        return self._json(_CANCEL_EVAL_RUN, _c.encoded_path("/evals/{}/runs/{}/cancel", eval_id, run_id), None, None, include_response)

    @_t.overload
    def get_eval_run_output_items(self, eval_id: str, run_id: str, *, params: _T.GetEvalRunOutputItemsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetEvalRunOutputItems200, _Errors]: ...
    @_t.overload
    def get_eval_run_output_items(self, eval_id: str, run_id: str, *, params: _T.GetEvalRunOutputItemsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetEvalRunOutputItems200, _HttpClientResponse], _Errors]: ...
    def get_eval_run_output_items(self, eval_id: str, run_id: str, *, params: _T.GetEvalRunOutputItemsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a list of output items for an evaluation run."""
        return self._json(_GET_EVAL_RUN_OUTPUT_ITEMS, _c.encoded_path("/evals/{}/runs/{}/output_items", eval_id, run_id), params, None, include_response)

    @_t.overload
    def get_eval_run_output_item(self, eval_id: str, run_id: str, output_item_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetEvalRunOutputItem200, _Errors]: ...
    @_t.overload
    def get_eval_run_output_item(self, eval_id: str, run_id: str, output_item_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetEvalRunOutputItem200, _HttpClientResponse], _Errors]: ...
    def get_eval_run_output_item(self, eval_id: str, run_id: str, output_item_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get an evaluation run output item by ID."""
        return self._json(_GET_EVAL_RUN_OUTPUT_ITEM, _c.encoded_path("/evals/{}/runs/{}/output_items/{}", eval_id, run_id, output_item_id), None, None, include_response)

    @_t.overload
    def list_files(self, *, params: _T.ListFilesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListFiles200, _Errors]: ...
    @_t.overload
    def list_files(self, *, params: _T.ListFilesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListFiles200, _HttpClientResponse], _Errors]: ...
    def list_files(self, *, params: _T.ListFilesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of files."""
        return self._json(_LIST_FILES, "/files", params, None, include_response)

    @_t.overload
    def create_file(self, *, payload: _T.CreateFileRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateFile200, _Errors]: ...
    @_t.overload
    def create_file(self, *, payload: _T.CreateFileRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateFile200, _HttpClientResponse], _Errors]: ...
    def create_file(self, *, payload: _T.CreateFileRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Upload a file that can be used across various endpoints. Individual files
        can be up to 512 MB, and each project can store up to 2.5 TB of files in
        total. There is no organization-wide storage limit. Uploads to this
        endpoint are rate-limited to 1,000 requests per minute per authenticated
        user.
        
        - The Assistants API supports files up to 2 million tokens and of specific
          file types. See the [Assistants Tools guide](https://developers.openai.com/api/docs/guides/tools) for
          details.
        - The Fine-tuning API only supports `.jsonl` files. The input also has
          certain required formats for fine-tuning
          [chat](https://developers.openai.com/api/docs/guides/supervised-fine-tuning#formatting-your-data) or
          [completions](https://developers.openai.com/api/docs/guides/supervised-fine-tuning#formatting-your-data) models.
        - The Batch API only supports `.jsonl` files up to 200 MB in size. The input
          also has a specific required
          [format](https://developers.openai.com/api/docs/guides/batch#1-prepare-your-batch-file).
        - For Retrieval or `file_search` ingestion, upload files here first. If
          you need to attach multiple uploaded files to the same vector store, use
          [`/vector_stores/{vector_store_id}/file_batches`](https://developers.openai.com/api/reference/resources/vector_stores/subresources/file_batches/methods/create)
          instead of attaching them one by one. Vector store attachment has separate
          limits from file upload, including 2,000 attached files per minute per
          organization.
        
        Please [contact us](https://help.openai.com/) if you need to increase these
        storage limits."""
        return self._json(_CREATE_FILE, "/files", None, _c.form_body(payload), include_response)

    @_t.overload
    def retrieve_file(self, file_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveFile200, _Errors]: ...
    @_t.overload
    def retrieve_file(self, file_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveFile200, _HttpClientResponse], _Errors]: ...
    def retrieve_file(self, file_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns information about a specific file."""
        return self._json(_RETRIEVE_FILE, _c.encoded_path("/files/{}", file_id), None, None, include_response)

    @_t.overload
    def delete_file(self, file_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteFile200, _Errors]: ...
    @_t.overload
    def delete_file(self, file_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteFile200, _HttpClientResponse], _Errors]: ...
    def delete_file(self, file_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a file and remove it from all vector stores."""
        return self._json(_DELETE_FILE, _c.encoded_path("/files/{}", file_id), None, None, include_response)

    @_t.overload
    def download_file(self, file_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def download_file(self, file_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def download_file(self, file_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a response containing the contents of the specified file."""
        return self._json(_DOWNLOAD_FILE, _c.encoded_path("/files/{}/content", file_id), None, None, include_response)

    def download_file_stream(self, file_id: str) -> _Stream[bytes, _HttpClientError]:
        """Returns a response containing the contents of the specified file."""
        return self._binary(_DOWNLOAD_FILE_STREAM, _c.encoded_path("/files/{}/content", file_id), None, None)

    @_t.overload
    def run_grader(self, *, payload: _T.RunGraderRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.RunGrader200, _Errors]: ...
    @_t.overload
    def run_grader(self, *, payload: _T.RunGraderRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RunGrader200, _HttpClientResponse], _Errors]: ...
    def run_grader(self, *, payload: _T.RunGraderRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Run a grader."""
        return self._json(_RUN_GRADER, "/fine_tuning/alpha/graders/run", None, _c.json_body(payload), include_response)

    @_t.overload
    def validate_grader(self, *, payload: _T.ValidateGraderRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ValidateGrader200, _Errors]: ...
    @_t.overload
    def validate_grader(self, *, payload: _T.ValidateGraderRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ValidateGrader200, _HttpClientResponse], _Errors]: ...
    def validate_grader(self, *, payload: _T.ValidateGraderRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Validate a grader."""
        return self._json(_VALIDATE_GRADER, "/fine_tuning/alpha/graders/validate", None, _c.json_body(payload), include_response)

    @_t.overload
    def list_fine_tuning_checkpoint_permissions(self, fine_tuned_model_checkpoint: str, *, params: _T.ListFineTuningCheckpointPermissionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListFineTuningCheckpointPermissions200, _Errors]: ...
    @_t.overload
    def list_fine_tuning_checkpoint_permissions(self, fine_tuned_model_checkpoint: str, *, params: _T.ListFineTuningCheckpointPermissionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListFineTuningCheckpointPermissions200, _HttpClientResponse], _Errors]: ...
    def list_fine_tuning_checkpoint_permissions(self, fine_tuned_model_checkpoint: str, *, params: _T.ListFineTuningCheckpointPermissionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """**NOTE:** This endpoint requires an [admin API key](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/admin_api_keys).
        
        Organization owners can use this endpoint to view all permissions for a fine-tuned model checkpoint."""
        return self._json(_LIST_FINE_TUNING_CHECKPOINT_PERMISSIONS, _c.encoded_path("/fine_tuning/checkpoints/{}/permissions", fine_tuned_model_checkpoint), params, None, include_response)

    @_t.overload
    def create_fine_tuning_checkpoint_permission(self, fine_tuned_model_checkpoint: str, *, payload: _T.CreateFineTuningCheckpointPermissionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateFineTuningCheckpointPermission200, _Errors]: ...
    @_t.overload
    def create_fine_tuning_checkpoint_permission(self, fine_tuned_model_checkpoint: str, *, payload: _T.CreateFineTuningCheckpointPermissionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateFineTuningCheckpointPermission200, _HttpClientResponse], _Errors]: ...
    def create_fine_tuning_checkpoint_permission(self, fine_tuned_model_checkpoint: str, *, payload: _T.CreateFineTuningCheckpointPermissionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """**NOTE:** Calling this endpoint requires an [admin API key](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/admin_api_keys).
        
        This enables organization owners to share fine-tuned models with other projects in their organization."""
        return self._json(_CREATE_FINE_TUNING_CHECKPOINT_PERMISSION, _c.encoded_path("/fine_tuning/checkpoints/{}/permissions", fine_tuned_model_checkpoint), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_fine_tuning_checkpoint_permission(self, fine_tuned_model_checkpoint: str, permission_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteFineTuningCheckpointPermission200, _Errors]: ...
    @_t.overload
    def delete_fine_tuning_checkpoint_permission(self, fine_tuned_model_checkpoint: str, permission_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteFineTuningCheckpointPermission200, _HttpClientResponse], _Errors]: ...
    def delete_fine_tuning_checkpoint_permission(self, fine_tuned_model_checkpoint: str, permission_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """**NOTE:** This endpoint requires an [admin API key](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/admin_api_keys).
        
        Organization owners can use this endpoint to delete a permission for a fine-tuned model checkpoint."""
        return self._json(_DELETE_FINE_TUNING_CHECKPOINT_PERMISSION, _c.encoded_path("/fine_tuning/checkpoints/{}/permissions/{}", fine_tuned_model_checkpoint, permission_id), None, None, include_response)

    @_t.overload
    def list_paginated_fine_tuning_jobs(self, *, params: _T.ListPaginatedFineTuningJobsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListPaginatedFineTuningJobs200, _Errors]: ...
    @_t.overload
    def list_paginated_fine_tuning_jobs(self, *, params: _T.ListPaginatedFineTuningJobsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListPaginatedFineTuningJobs200, _HttpClientResponse], _Errors]: ...
    def list_paginated_fine_tuning_jobs(self, *, params: _T.ListPaginatedFineTuningJobsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List your organization's fine-tuning jobs"""
        return self._json(_LIST_PAGINATED_FINE_TUNING_JOBS, "/fine_tuning/jobs", params, None, include_response)

    @_t.overload
    def create_fine_tuning_job(self, *, payload: _T.CreateFineTuningJobRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateFineTuningJob200, _Errors]: ...
    @_t.overload
    def create_fine_tuning_job(self, *, payload: _T.CreateFineTuningJobRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateFineTuningJob200, _HttpClientResponse], _Errors]: ...
    def create_fine_tuning_job(self, *, payload: _T.CreateFineTuningJobRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a fine-tuning job which begins the process of creating a new model from a given dataset.
        
        Response includes details of the enqueued job including job status and the name of the fine-tuned models once complete.
        
        [Learn more about fine-tuning](https://developers.openai.com/api/docs/guides/model-optimization)"""
        return self._json(_CREATE_FINE_TUNING_JOB, "/fine_tuning/jobs", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveFineTuningJob200, _Errors]: ...
    @_t.overload
    def retrieve_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveFineTuningJob200, _HttpClientResponse], _Errors]: ...
    def retrieve_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get info about a fine-tuning job.
        
        [Learn more about fine-tuning](https://developers.openai.com/api/docs/guides/model-optimization)"""
        return self._json(_RETRIEVE_FINE_TUNING_JOB, _c.encoded_path("/fine_tuning/jobs/{}", fine_tuning_job_id), None, None, include_response)

    @_t.overload
    def cancel_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.CancelFineTuningJob200, _Errors]: ...
    @_t.overload
    def cancel_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CancelFineTuningJob200, _HttpClientResponse], _Errors]: ...
    def cancel_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Immediately cancel a fine-tune job."""
        return self._json(_CANCEL_FINE_TUNING_JOB, _c.encoded_path("/fine_tuning/jobs/{}/cancel", fine_tuning_job_id), None, None, include_response)

    @_t.overload
    def list_fine_tuning_job_checkpoints(self, fine_tuning_job_id: str, *, params: _T.ListFineTuningJobCheckpointsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListFineTuningJobCheckpoints200, _Errors]: ...
    @_t.overload
    def list_fine_tuning_job_checkpoints(self, fine_tuning_job_id: str, *, params: _T.ListFineTuningJobCheckpointsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListFineTuningJobCheckpoints200, _HttpClientResponse], _Errors]: ...
    def list_fine_tuning_job_checkpoints(self, fine_tuning_job_id: str, *, params: _T.ListFineTuningJobCheckpointsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List checkpoints for a fine-tuning job."""
        return self._json(_LIST_FINE_TUNING_JOB_CHECKPOINTS, _c.encoded_path("/fine_tuning/jobs/{}/checkpoints", fine_tuning_job_id), params, None, include_response)

    @_t.overload
    def list_fine_tuning_events(self, fine_tuning_job_id: str, *, params: _T.ListFineTuningEventsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListFineTuningEvents200, _Errors]: ...
    @_t.overload
    def list_fine_tuning_events(self, fine_tuning_job_id: str, *, params: _T.ListFineTuningEventsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListFineTuningEvents200, _HttpClientResponse], _Errors]: ...
    def list_fine_tuning_events(self, fine_tuning_job_id: str, *, params: _T.ListFineTuningEventsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get status updates for a fine-tuning job."""
        return self._json(_LIST_FINE_TUNING_EVENTS, _c.encoded_path("/fine_tuning/jobs/{}/events", fine_tuning_job_id), params, None, include_response)

    @_t.overload
    def pause_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.PauseFineTuningJob200, _Errors]: ...
    @_t.overload
    def pause_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.PauseFineTuningJob200, _HttpClientResponse], _Errors]: ...
    def pause_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Pause a fine-tune job."""
        return self._json(_PAUSE_FINE_TUNING_JOB, _c.encoded_path("/fine_tuning/jobs/{}/pause", fine_tuning_job_id), None, None, include_response)

    @_t.overload
    def resume_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.ResumeFineTuningJob200, _Errors]: ...
    @_t.overload
    def resume_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ResumeFineTuningJob200, _HttpClientResponse], _Errors]: ...
    def resume_fine_tuning_job(self, fine_tuning_job_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Resume a fine-tune job."""
        return self._json(_RESUME_FINE_TUNING_JOB, _c.encoded_path("/fine_tuning/jobs/{}/resume", fine_tuning_job_id), None, None, include_response)

    @_t.overload
    def create_image_edit(self, *, payload: _T.CreateImageEditRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateImageEdit200, _Errors]: ...
    @_t.overload
    def create_image_edit(self, *, payload: _T.CreateImageEditRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateImageEdit200, _HttpClientResponse], _Errors]: ...
    def create_image_edit(self, *, payload: _T.CreateImageEditRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates an edited or extended image given one or more source images and a prompt. This endpoint supports GPT Image models."""
        return self._json(_CREATE_IMAGE_EDIT, "/images/edits", None, _c.form_body(payload), include_response)

    def create_image_edit_sse(self, *, payload: _T.CreateImageEditRequestFormData) -> _Stream[_sse.DataEvent[_T.CreateImageEdit200Sse], _SseErrors]:
        """Creates an edited or extended image given one or more source images and a prompt. This endpoint supports GPT Image models."""
        return self._sse(_CREATE_IMAGE_EDIT_SSE, "/images/edits", None, _c.form_body(payload), CreateImageEdit200Sse)

    @_t.overload
    def create_image(self, *, payload: _T.CreateImageRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateImage200, _Errors]: ...
    @_t.overload
    def create_image(self, *, payload: _T.CreateImageRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateImage200, _HttpClientResponse], _Errors]: ...
    def create_image(self, *, payload: _T.CreateImageRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates an image given a prompt using a GPT Image model. [Learn more](https://developers.openai.com/api/docs/guides/images-vision)."""
        return self._json(_CREATE_IMAGE, "/images/generations", None, _c.json_body(payload), include_response)

    def create_image_sse(self, *, payload: _T.CreateImageRequestJson) -> _Stream[_sse.DataEvent[_T.CreateImage200Sse], _SseErrors]:
        """Creates an image given a prompt using a GPT Image model. [Learn more](https://developers.openai.com/api/docs/guides/images-vision)."""
        return self._sse(_CREATE_IMAGE_SSE, "/images/generations", None, _c.json_body(payload), CreateImage200Sse)

    @_t.overload
    def create_image_variation(self, *, payload: _T.CreateImageVariationRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateImageVariation200, _Errors]: ...
    @_t.overload
    def create_image_variation(self, *, payload: _T.CreateImageVariationRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateImageVariation200, _HttpClientResponse], _Errors]: ...
    def create_image_variation(self, *, payload: _T.CreateImageVariationRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """This endpoint is retired and no longer available. Use the image edits endpoint with a GPT Image model and a prompt to create a variation of an image. The request and response schemas below describe the legacy contract."""
        return self._json(_CREATE_IMAGE_VARIATION, "/images/variations", None, _c.form_body(payload), include_response)

    @_t.overload
    def create_live(self, *, payload: _T.CreateLiveRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateLive201, _Errors]: ...
    @_t.overload
    def create_live(self, *, payload: _T.CreateLiveRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateLive201, _HttpClientResponse], _Errors]: ...
    def create_live(self, *, payload: _T.CreateLiveRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a Live WebRTC session or place an outbound SIP call. Start with the
        [Live prompting guide](https://developers.openai.com/api/docs/guides/live-prompting) for session configuration
        and [Telephony and SIP](https://developers.openai.com/api/docs/guides/voice-sip?api=live#place-an-outbound-call)
        for trunk setup and call monitoring.
        
        Set transport.type to `webrtc` and supply an SDP offer, or set it to `sip`
        and supply an E.164 destination and trunk credentials. Outbound SIP calling
        must be enabled for your organization.
        Ringing is limited to 3 minutes and connected calls to 2 hours; these limits
        are not configurable in the request.
        
        Returns `201 Created` after session initialization. WebRTC responses include an
        SDP answer. SIP responses do not wait for the callee to answer. Attach a
        sideband connection using session.id to monitor SIP call progress.
        
        Each SIP request creates a new call. If a request times out or the connection
        fails, retry with caution: the original request may have succeeded, and a
        retry can place another call."""
        return self._json(_CREATE_LIVE, "/live/sessions", None, _c.json_body(payload), include_response)

    @_t.overload
    def accept_live_session(self, session_id: str, *, payload: _T.AcceptLiveSessionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def accept_live_session(self, session_id: str, *, payload: _T.AcceptLiveSessionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def accept_live_session(self, session_id: str, *, payload: _T.AcceptLiveSessionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Accept an incoming SIP call. Supply session with type live, the model, and startup configuration. Before accepting calls, follow the [Live prompting guide](https://developers.openai.com/api/docs/guides/live-prompting) to write frontend conversation instructions and a separate backend prompt. SIP media format is negotiated; omit audio.format."""
        return self._json(_ACCEPT_LIVE_SESSION, _c.encoded_path("/live/sessions/{}/accept", session_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def fork_live_session(self, session_id: str, *, payload: _T.ForkLiveSessionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ForkLiveSession201, _Errors]: ...
    @_t.overload
    def fork_live_session(self, session_id: str, *, payload: _T.ForkLiveSessionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ForkLiveSession201, _HttpClientResponse], _Errors]: ...
    def fork_live_session(self, session_id: str, *, payload: _T.ForkLiveSessionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Fork a stored Live session onto a new WebRTC connection."""
        return self._json(_FORK_LIVE_SESSION, _c.encoded_path("/live/sessions/{}/fork", session_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def hangup_live_session(self, session_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def hangup_live_session(self, session_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def hangup_live_session(self, session_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """End a SIP call identified by session_id."""
        return self._json(_HANGUP_LIVE_SESSION, _c.encoded_path("/live/sessions/{}/hangup", session_id), None, None, include_response)

    @_t.overload
    def refer_live_session(self, session_id: str, *, payload: _T.ReferLiveSessionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def refer_live_session(self, session_id: str, *, payload: _T.ReferLiveSessionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def refer_live_session(self, session_id: str, *, payload: _T.ReferLiveSessionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Transfer a SIP call to another destination. Supply a nonblank target_uri for the SIP Refer-To header."""
        return self._json(_REFER_LIVE_SESSION, _c.encoded_path("/live/sessions/{}/refer", session_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def reject_live_session(self, session_id: str, *, payload: _T.RejectLiveSessionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def reject_live_session(self, session_id: str, *, payload: _T.RejectLiveSessionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def reject_live_session(self, session_id: str, *, payload: _T.RejectLiveSessionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Reject an incoming SIP call. Send a required SIP rejection status_code between 300 and 699."""
        return self._json(_REJECT_LIVE_SESSION, _c.encoded_path("/live/sessions/{}/reject", session_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def list_models(self, *, include_response: _t.Literal[False] = False) -> _Effect[_T.ListModels200, _Errors]: ...
    @_t.overload
    def list_models(self, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListModels200, _HttpClientResponse], _Errors]: ...
    def list_models(self, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the currently available models, and provides basic information about each one such as the owner and availability."""
        return self._json(_LIST_MODELS, "/models", None, None, include_response)

    @_t.overload
    def retrieve_model(self, model: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveModel200, _Errors]: ...
    @_t.overload
    def retrieve_model(self, model: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveModel200, _HttpClientResponse], _Errors]: ...
    def retrieve_model(self, model: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a model instance, providing basic information about the model such as the owner and permissioning."""
        return self._json(_RETRIEVE_MODEL, _c.encoded_path("/models/{}", model), None, None, include_response)

    @_t.overload
    def delete_model(self, model: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteModel200, _Errors]: ...
    @_t.overload
    def delete_model(self, model: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteModel200, _HttpClientResponse], _Errors]: ...
    def delete_model(self, model: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a fine-tuned model. You must have the Owner role in your organization to delete a model."""
        return self._json(_DELETE_MODEL, _c.encoded_path("/models/{}", model), None, None, include_response)

    @_t.overload
    def create_moderation(self, *, payload: _T.CreateModerationRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateModeration200, _Errors]: ...
    @_t.overload
    def create_moderation(self, *, payload: _T.CreateModerationRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateModeration200, _HttpClientResponse], _Errors]: ...
    def create_moderation(self, *, payload: _T.CreateModerationRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Classifies if text and/or image inputs are potentially harmful. Learn
        more in the [moderation guide](https://developers.openai.com/api/docs/guides/moderation)."""
        return self._json(_CREATE_MODERATION, "/moderations", None, _c.json_body(payload), include_response)

    @_t.overload
    def admin_api_keys_list(self, *, params: _T.AdminApiKeysListParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.AdminApiKeysList200, _Errors]: ...
    @_t.overload
    def admin_api_keys_list(self, *, params: _T.AdminApiKeysListParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AdminApiKeysList200, _HttpClientResponse], _Errors]: ...
    def admin_api_keys_list(self, *, params: _T.AdminApiKeysListParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List organization API keys"""
        return self._json(_ADMIN_API_KEYS_LIST, "/organization/admin_api_keys", params, None, include_response)

    @_t.overload
    def admin_api_keys_create(self, *, payload: _T.AdminApiKeysCreateRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.AdminApiKeysCreate200, _Errors]: ...
    @_t.overload
    def admin_api_keys_create(self, *, payload: _T.AdminApiKeysCreateRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AdminApiKeysCreate200, _HttpClientResponse], _Errors]: ...
    def admin_api_keys_create(self, *, payload: _T.AdminApiKeysCreateRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create an organization admin API key"""
        return self._json(_ADMIN_API_KEYS_CREATE, "/organization/admin_api_keys", None, _c.json_body(payload), include_response)

    @_t.overload
    def admin_api_keys_get(self, key_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.AdminApiKeysGet200, _Errors]: ...
    @_t.overload
    def admin_api_keys_get(self, key_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AdminApiKeysGet200, _HttpClientResponse], _Errors]: ...
    def admin_api_keys_get(self, key_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieve a single organization API key"""
        return self._json(_ADMIN_API_KEYS_GET, _c.encoded_path("/organization/admin_api_keys/{}", key_id), None, None, include_response)

    @_t.overload
    def admin_api_keys_delete(self, key_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.AdminApiKeysDelete200, _Errors]: ...
    @_t.overload
    def admin_api_keys_delete(self, key_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AdminApiKeysDelete200, _HttpClientResponse], _Errors]: ...
    def admin_api_keys_delete(self, key_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an organization admin API key"""
        return self._json(_ADMIN_API_KEYS_DELETE, _c.encoded_path("/organization/admin_api_keys/{}", key_id), None, None, include_response)

    @_t.overload
    def list_audit_logs(self, *, params: _T.ListAuditLogsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAuditLogs200, _Errors]: ...
    @_t.overload
    def list_audit_logs(self, *, params: _T.ListAuditLogsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAuditLogs200, _HttpClientResponse], _Errors]: ...
    def list_audit_logs(self, *, params: _T.ListAuditLogsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List user actions and configuration changes within this organization."""
        return self._json(_LIST_AUDIT_LOGS, "/organization/audit_logs", params, None, include_response)

    @_t.overload
    def list_organization_certificates(self, *, params: _T.ListOrganizationCertificatesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListOrganizationCertificates200, _Errors]: ...
    @_t.overload
    def list_organization_certificates(self, *, params: _T.ListOrganizationCertificatesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListOrganizationCertificates200, _HttpClientResponse], _Errors]: ...
    def list_organization_certificates(self, *, params: _T.ListOrganizationCertificatesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List uploaded certificates for this organization."""
        return self._json(_LIST_ORGANIZATION_CERTIFICATES, "/organization/certificates", params, None, include_response)

    @_t.overload
    def upload_certificate(self, *, payload: _T.UploadCertificateRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UploadCertificate200, _Errors]: ...
    @_t.overload
    def upload_certificate(self, *, payload: _T.UploadCertificateRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UploadCertificate200, _HttpClientResponse], _Errors]: ...
    def upload_certificate(self, *, payload: _T.UploadCertificateRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Upload a certificate to the organization. This does **not** automatically activate the certificate.
        
        Organizations can upload up to 50 certificates."""
        return self._json(_UPLOAD_CERTIFICATE, "/organization/certificates", None, _c.json_body(payload), include_response)

    @_t.overload
    def activate_organization_certificates(self, *, payload: _T.ActivateOrganizationCertificatesRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ActivateOrganizationCertificates200, _Errors]: ...
    @_t.overload
    def activate_organization_certificates(self, *, payload: _T.ActivateOrganizationCertificatesRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ActivateOrganizationCertificates200, _HttpClientResponse], _Errors]: ...
    def activate_organization_certificates(self, *, payload: _T.ActivateOrganizationCertificatesRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Activate certificates at the organization level.
        
        You can atomically and idempotently activate up to 10 certificates at a time."""
        return self._json(_ACTIVATE_ORGANIZATION_CERTIFICATES, "/organization/certificates/activate", None, _c.json_body(payload), include_response)

    @_t.overload
    def deactivate_organization_certificates(self, *, payload: _T.DeactivateOrganizationCertificatesRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.DeactivateOrganizationCertificates200, _Errors]: ...
    @_t.overload
    def deactivate_organization_certificates(self, *, payload: _T.DeactivateOrganizationCertificatesRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeactivateOrganizationCertificates200, _HttpClientResponse], _Errors]: ...
    def deactivate_organization_certificates(self, *, payload: _T.DeactivateOrganizationCertificatesRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deactivate certificates at the organization level.
        
        You can atomically and idempotently deactivate up to 10 certificates at a time."""
        return self._json(_DEACTIVATE_ORGANIZATION_CERTIFICATES, "/organization/certificates/deactivate", None, _c.json_body(payload), include_response)

    @_t.overload
    def get_certificate(self, certificate_id: str, *, params: _T.GetCertificateParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetCertificate200, _Errors]: ...
    @_t.overload
    def get_certificate(self, certificate_id: str, *, params: _T.GetCertificateParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetCertificate200, _HttpClientResponse], _Errors]: ...
    def get_certificate(self, certificate_id: str, *, params: _T.GetCertificateParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a certificate that has been uploaded to the organization.
        
        You can get a certificate regardless of whether it is active or not."""
        return self._json(_GET_CERTIFICATE, _c.encoded_path("/organization/certificates/{}", certificate_id), params, None, include_response)

    @_t.overload
    def modify_certificate(self, certificate_id: str, *, payload: _T.ModifyCertificateRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ModifyCertificate200, _Errors]: ...
    @_t.overload
    def modify_certificate(self, certificate_id: str, *, payload: _T.ModifyCertificateRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ModifyCertificate200, _HttpClientResponse], _Errors]: ...
    def modify_certificate(self, certificate_id: str, *, payload: _T.ModifyCertificateRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Modify a certificate. Note that only the name can be modified."""
        return self._json(_MODIFY_CERTIFICATE, _c.encoded_path("/organization/certificates/{}", certificate_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_certificate(self, certificate_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteCertificate200, _Errors]: ...
    @_t.overload
    def delete_certificate(self, certificate_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteCertificate200, _HttpClientResponse], _Errors]: ...
    def delete_certificate(self, certificate_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a certificate from the organization.
        
        The certificate must be inactive for the organization and all projects."""
        return self._json(_DELETE_CERTIFICATE, _c.encoded_path("/organization/certificates/{}", certificate_id), None, None, include_response)

    @_t.overload
    def usage_costs(self, *, params: _T.UsageCostsParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageCosts200, _Errors]: ...
    @_t.overload
    def usage_costs(self, *, params: _T.UsageCostsParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageCosts200, _HttpClientResponse], _Errors]: ...
    def usage_costs(self, *, params: _T.UsageCostsParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get costs details for the organization."""
        return self._json(_USAGE_COSTS, "/organization/costs", params, None, include_response)

    @_t.overload
    def retrieve_organization_data_retention(self, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveOrganizationDataRetention200, _Errors]: ...
    @_t.overload
    def retrieve_organization_data_retention(self, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveOrganizationDataRetention200, _HttpClientResponse], _Errors]: ...
    def retrieve_organization_data_retention(self, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves organization data retention controls."""
        return self._json(_RETRIEVE_ORGANIZATION_DATA_RETENTION, "/organization/data_retention", None, None, include_response)

    @_t.overload
    def update_organization_data_retention(self, *, payload: _T.UpdateOrganizationDataRetentionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateOrganizationDataRetention200, _Errors]: ...
    @_t.overload
    def update_organization_data_retention(self, *, payload: _T.UpdateOrganizationDataRetentionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateOrganizationDataRetention200, _HttpClientResponse], _Errors]: ...
    def update_organization_data_retention(self, *, payload: _T.UpdateOrganizationDataRetentionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates organization data retention controls."""
        return self._json(_UPDATE_ORGANIZATION_DATA_RETENTION, "/organization/data_retention", None, _c.json_body(payload), include_response)

    @_t.overload
    def list_groups(self, *, params: _T.ListGroupsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListGroups200, _Errors]: ...
    @_t.overload
    def list_groups(self, *, params: _T.ListGroupsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListGroups200, _HttpClientResponse], _Errors]: ...
    def list_groups(self, *, params: _T.ListGroupsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists all groups in the organization."""
        return self._json(_LIST_GROUPS, "/organization/groups", params, None, include_response)

    @_t.overload
    def create_group(self, *, payload: _T.CreateGroupRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateGroup200, _Errors]: ...
    @_t.overload
    def create_group(self, *, payload: _T.CreateGroupRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateGroup200, _HttpClientResponse], _Errors]: ...
    def create_group(self, *, payload: _T.CreateGroupRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a new group in the organization."""
        return self._json(_CREATE_GROUP, "/organization/groups", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_group(self, group_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveGroup200, _Errors]: ...
    @_t.overload
    def retrieve_group(self, group_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveGroup200, _HttpClientResponse], _Errors]: ...
    def retrieve_group(self, group_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a group."""
        return self._json(_RETRIEVE_GROUP, _c.encoded_path("/organization/groups/{}", group_id), None, None, include_response)

    @_t.overload
    def update_group(self, group_id: str, *, payload: _T.UpdateGroupRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateGroup200, _Errors]: ...
    @_t.overload
    def update_group(self, group_id: str, *, payload: _T.UpdateGroupRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateGroup200, _HttpClientResponse], _Errors]: ...
    def update_group(self, group_id: str, *, payload: _T.UpdateGroupRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates a group's information."""
        return self._json(_UPDATE_GROUP, _c.encoded_path("/organization/groups/{}", group_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_group(self, group_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteGroup200, _Errors]: ...
    @_t.overload
    def delete_group(self, group_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteGroup200, _HttpClientResponse], _Errors]: ...
    def delete_group(self, group_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a group from the organization."""
        return self._json(_DELETE_GROUP, _c.encoded_path("/organization/groups/{}", group_id), None, None, include_response)

    @_t.overload
    def list_group_role_assignments(self, group_id: str, *, params: _T.ListGroupRoleAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListGroupRoleAssignments200, _Errors]: ...
    @_t.overload
    def list_group_role_assignments(self, group_id: str, *, params: _T.ListGroupRoleAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListGroupRoleAssignments200, _HttpClientResponse], _Errors]: ...
    def list_group_role_assignments(self, group_id: str, *, params: _T.ListGroupRoleAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the organization roles assigned to a group within the organization."""
        return self._json(_LIST_GROUP_ROLE_ASSIGNMENTS, _c.encoded_path("/organization/groups/{}/roles", group_id), params, None, include_response)

    @_t.overload
    def assign_group_role(self, group_id: str, *, payload: _T.AssignGroupRoleRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.AssignGroupRole200, _Errors]: ...
    @_t.overload
    def assign_group_role(self, group_id: str, *, payload: _T.AssignGroupRoleRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AssignGroupRole200, _HttpClientResponse], _Errors]: ...
    def assign_group_role(self, group_id: str, *, payload: _T.AssignGroupRoleRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Assigns an organization role to a group within the organization."""
        return self._json(_ASSIGN_GROUP_ROLE, _c.encoded_path("/organization/groups/{}/roles", group_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_group_role(self, group_id: str, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveGroupRole200, _Errors]: ...
    @_t.overload
    def retrieve_group_role(self, group_id: str, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveGroupRole200, _HttpClientResponse], _Errors]: ...
    def retrieve_group_role(self, group_id: str, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves an organization role assigned to a group."""
        return self._json(_RETRIEVE_GROUP_ROLE, _c.encoded_path("/organization/groups/{}/roles/{}", group_id, role_id), None, None, include_response)

    @_t.overload
    def unassign_group_role(self, group_id: str, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.UnassignGroupRole200, _Errors]: ...
    @_t.overload
    def unassign_group_role(self, group_id: str, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UnassignGroupRole200, _HttpClientResponse], _Errors]: ...
    def unassign_group_role(self, group_id: str, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Unassigns an organization role from a group within the organization."""
        return self._json(_UNASSIGN_GROUP_ROLE, _c.encoded_path("/organization/groups/{}/roles/{}", group_id, role_id), None, None, include_response)

    @_t.overload
    def list_group_users(self, group_id: str, *, params: _T.ListGroupUsersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListGroupUsers200, _Errors]: ...
    @_t.overload
    def list_group_users(self, group_id: str, *, params: _T.ListGroupUsersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListGroupUsers200, _HttpClientResponse], _Errors]: ...
    def list_group_users(self, group_id: str, *, params: _T.ListGroupUsersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the users assigned to a group."""
        return self._json(_LIST_GROUP_USERS, _c.encoded_path("/organization/groups/{}/users", group_id), params, None, include_response)

    @_t.overload
    def add_group_user(self, group_id: str, *, payload: _T.AddGroupUserRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.AddGroupUser200, _Errors]: ...
    @_t.overload
    def add_group_user(self, group_id: str, *, payload: _T.AddGroupUserRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AddGroupUser200, _HttpClientResponse], _Errors]: ...
    def add_group_user(self, group_id: str, *, payload: _T.AddGroupUserRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Adds a user to a group."""
        return self._json(_ADD_GROUP_USER, _c.encoded_path("/organization/groups/{}/users", group_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_group_user(self, group_id: str, user_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveGroupUser200, _Errors]: ...
    @_t.overload
    def retrieve_group_user(self, group_id: str, user_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveGroupUser200, _HttpClientResponse], _Errors]: ...
    def retrieve_group_user(self, group_id: str, user_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a user in a group."""
        return self._json(_RETRIEVE_GROUP_USER, _c.encoded_path("/organization/groups/{}/users/{}", group_id, user_id), None, None, include_response)

    @_t.overload
    def remove_group_user(self, group_id: str, user_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RemoveGroupUser200, _Errors]: ...
    @_t.overload
    def remove_group_user(self, group_id: str, user_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RemoveGroupUser200, _HttpClientResponse], _Errors]: ...
    def remove_group_user(self, group_id: str, user_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Removes a user from a group."""
        return self._json(_REMOVE_GROUP_USER, _c.encoded_path("/organization/groups/{}/users/{}", group_id, user_id), None, None, include_response)

    @_t.overload
    def list_invites(self, *, params: _T.ListInvitesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListInvites200, _Errors]: ...
    @_t.overload
    def list_invites(self, *, params: _T.ListInvitesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListInvites200, _HttpClientResponse], _Errors]: ...
    def list_invites(self, *, params: _T.ListInvitesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of invites in the organization."""
        return self._json(_LIST_INVITES, "/organization/invites", params, None, include_response)

    @_t.overload
    def invite_user(self, *, payload: _T.InviteUserRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.InviteUser200 | _T.InviteUser201, _Errors]: ...
    @_t.overload
    def invite_user(self, *, payload: _T.InviteUserRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.InviteUser200 | _T.InviteUser201, _HttpClientResponse], _Errors]: ...
    def invite_user(self, *, payload: _T.InviteUserRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create an invite for a user to the organization. The invite must be accepted by the user before they have access to the organization."""
        return self._json(_INVITE_USER, "/organization/invites", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_invite(self, invite_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveInvite200, _Errors]: ...
    @_t.overload
    def retrieve_invite(self, invite_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveInvite200, _HttpClientResponse], _Errors]: ...
    def retrieve_invite(self, invite_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves an invite."""
        return self._json(_RETRIEVE_INVITE, _c.encoded_path("/organization/invites/{}", invite_id), None, None, include_response)

    @_t.overload
    def delete_invite(self, invite_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteInvite200, _Errors]: ...
    @_t.overload
    def delete_invite(self, invite_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteInvite200, _HttpClientResponse], _Errors]: ...
    def delete_invite(self, invite_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete an invite. If the invite has already been accepted, it cannot be deleted."""
        return self._json(_DELETE_INVITE, _c.encoded_path("/organization/invites/{}", invite_id), None, None, include_response)

    @_t.overload
    def list_projects(self, *, params: _T.ListProjectsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjects200, _Errors]: ...
    @_t.overload
    def list_projects(self, *, params: _T.ListProjectsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjects200, _HttpClientResponse], _Errors]: ...
    def list_projects(self, *, params: _T.ListProjectsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of projects."""
        return self._json(_LIST_PROJECTS, "/organization/projects", params, None, include_response)

    @_t.overload
    def create_project(self, *, payload: _T.CreateProjectRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateProject200 | _T.CreateProject201, _Errors]: ...
    @_t.overload
    def create_project(self, *, payload: _T.CreateProjectRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateProject200 | _T.CreateProject201, _HttpClientResponse], _Errors]: ...
    def create_project(self, *, payload: _T.CreateProjectRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new project in the organization. Projects can be created and archived, but cannot be deleted."""
        return self._json(_CREATE_PROJECT, "/organization/projects", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_project(self, project_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProject200, _Errors]: ...
    @_t.overload
    def retrieve_project(self, project_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProject200, _HttpClientResponse], _Errors]: ...
    def retrieve_project(self, project_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a project."""
        return self._json(_RETRIEVE_PROJECT, _c.encoded_path("/organization/projects/{}", project_id), None, None, include_response)

    @_t.overload
    def modify_project(self, project_id: str, *, payload: _T.ModifyProjectRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ModifyProject200, _Errors]: ...
    @_t.overload
    def modify_project(self, project_id: str, *, payload: _T.ModifyProjectRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ModifyProject200, _HttpClientResponse], _Errors]: ...
    def modify_project(self, project_id: str, *, payload: _T.ModifyProjectRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Modifies a project in the organization."""
        return self._json(_MODIFY_PROJECT, _c.encoded_path("/organization/projects/{}", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def list_project_api_keys(self, project_id: str, *, params: _T.ListProjectApiKeysParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjectApiKeys200, _Errors]: ...
    @_t.overload
    def list_project_api_keys(self, project_id: str, *, params: _T.ListProjectApiKeysParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjectApiKeys200, _HttpClientResponse], _Errors]: ...
    def list_project_api_keys(self, project_id: str, *, params: _T.ListProjectApiKeysParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of API keys in the project."""
        return self._json(_LIST_PROJECT_API_KEYS, _c.encoded_path("/organization/projects/{}/api_keys", project_id), params, None, include_response)

    @_t.overload
    def retrieve_project_api_key(self, project_id: str, api_key_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectApiKey200, _Errors]: ...
    @_t.overload
    def retrieve_project_api_key(self, project_id: str, api_key_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectApiKey200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_api_key(self, project_id: str, api_key_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves an API key in the project."""
        return self._json(_RETRIEVE_PROJECT_API_KEY, _c.encoded_path("/organization/projects/{}/api_keys/{}", project_id, api_key_id), None, None, include_response)

    @_t.overload
    def delete_project_api_key(self, project_id: str, api_key_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteProjectApiKey200, _Errors]: ...
    @_t.overload
    def delete_project_api_key(self, project_id: str, api_key_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteProjectApiKey200, _HttpClientResponse], _Errors]: ...
    def delete_project_api_key(self, project_id: str, api_key_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes an API key from the project.
        
        Returns confirmation of the key deletion, or an error if the key belonged to
        a service account."""
        return self._json(_DELETE_PROJECT_API_KEY, _c.encoded_path("/organization/projects/{}/api_keys/{}", project_id, api_key_id), None, None, include_response)

    @_t.overload
    def archive_project(self, project_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.ArchiveProject200, _Errors]: ...
    @_t.overload
    def archive_project(self, project_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ArchiveProject200, _HttpClientResponse], _Errors]: ...
    def archive_project(self, project_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Archives a project in the organization. Archived projects cannot be used or updated."""
        return self._json(_ARCHIVE_PROJECT, _c.encoded_path("/organization/projects/{}/archive", project_id), None, None, include_response)

    @_t.overload
    def list_project_certificates(self, project_id: str, *, params: _T.ListProjectCertificatesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjectCertificates200, _Errors]: ...
    @_t.overload
    def list_project_certificates(self, project_id: str, *, params: _T.ListProjectCertificatesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjectCertificates200, _HttpClientResponse], _Errors]: ...
    def list_project_certificates(self, project_id: str, *, params: _T.ListProjectCertificatesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List certificates for this project."""
        return self._json(_LIST_PROJECT_CERTIFICATES, _c.encoded_path("/organization/projects/{}/certificates", project_id), params, None, include_response)

    @_t.overload
    def activate_project_certificates(self, project_id: str, *, payload: _T.ActivateProjectCertificatesRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ActivateProjectCertificates200, _Errors]: ...
    @_t.overload
    def activate_project_certificates(self, project_id: str, *, payload: _T.ActivateProjectCertificatesRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ActivateProjectCertificates200, _HttpClientResponse], _Errors]: ...
    def activate_project_certificates(self, project_id: str, *, payload: _T.ActivateProjectCertificatesRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Activate certificates at the project level.
        
        You can atomically and idempotently activate up to 10 certificates at a time."""
        return self._json(_ACTIVATE_PROJECT_CERTIFICATES, _c.encoded_path("/organization/projects/{}/certificates/activate", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def deactivate_project_certificates(self, project_id: str, *, payload: _T.DeactivateProjectCertificatesRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.DeactivateProjectCertificates200, _Errors]: ...
    @_t.overload
    def deactivate_project_certificates(self, project_id: str, *, payload: _T.DeactivateProjectCertificatesRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeactivateProjectCertificates200, _HttpClientResponse], _Errors]: ...
    def deactivate_project_certificates(self, project_id: str, *, payload: _T.DeactivateProjectCertificatesRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deactivate certificates at the project level. You can atomically and
        idempotently deactivate up to 10 certificates at a time."""
        return self._json(_DEACTIVATE_PROJECT_CERTIFICATES, _c.encoded_path("/organization/projects/{}/certificates/deactivate", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_project_data_retention(self, project_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectDataRetention200, _Errors]: ...
    @_t.overload
    def retrieve_project_data_retention(self, project_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectDataRetention200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_data_retention(self, project_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves project data retention controls."""
        return self._json(_RETRIEVE_PROJECT_DATA_RETENTION, _c.encoded_path("/organization/projects/{}/data_retention", project_id), None, None, include_response)

    @_t.overload
    def update_project_data_retention(self, project_id: str, *, payload: _T.UpdateProjectDataRetentionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateProjectDataRetention200, _Errors]: ...
    @_t.overload
    def update_project_data_retention(self, project_id: str, *, payload: _T.UpdateProjectDataRetentionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateProjectDataRetention200, _HttpClientResponse], _Errors]: ...
    def update_project_data_retention(self, project_id: str, *, payload: _T.UpdateProjectDataRetentionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates project data retention controls."""
        return self._json(_UPDATE_PROJECT_DATA_RETENTION, _c.encoded_path("/organization/projects/{}/data_retention", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def list_project_groups(self, project_id: str, *, params: _T.ListProjectGroupsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjectGroups200, _Errors]: ...
    @_t.overload
    def list_project_groups(self, project_id: str, *, params: _T.ListProjectGroupsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjectGroups200, _HttpClientResponse], _Errors]: ...
    def list_project_groups(self, project_id: str, *, params: _T.ListProjectGroupsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the groups that have access to a project."""
        return self._json(_LIST_PROJECT_GROUPS, _c.encoded_path("/organization/projects/{}/groups", project_id), params, None, include_response)

    @_t.overload
    def add_project_group(self, project_id: str, *, payload: _T.AddProjectGroupRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.AddProjectGroup200, _Errors]: ...
    @_t.overload
    def add_project_group(self, project_id: str, *, payload: _T.AddProjectGroupRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AddProjectGroup200, _HttpClientResponse], _Errors]: ...
    def add_project_group(self, project_id: str, *, payload: _T.AddProjectGroupRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Grants a group access to a project."""
        return self._json(_ADD_PROJECT_GROUP, _c.encoded_path("/organization/projects/{}/groups", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_project_group(self, project_id: str, group_id: str, *, params: _T.RetrieveProjectGroupParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectGroup200, _Errors]: ...
    @_t.overload
    def retrieve_project_group(self, project_id: str, group_id: str, *, params: _T.RetrieveProjectGroupParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectGroup200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_group(self, project_id: str, group_id: str, *, params: _T.RetrieveProjectGroupParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a project's group."""
        return self._json(_RETRIEVE_PROJECT_GROUP, _c.encoded_path("/organization/projects/{}/groups/{}", project_id, group_id), params, None, include_response)

    @_t.overload
    def remove_project_group(self, project_id: str, group_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RemoveProjectGroup200, _Errors]: ...
    @_t.overload
    def remove_project_group(self, project_id: str, group_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RemoveProjectGroup200, _HttpClientResponse], _Errors]: ...
    def remove_project_group(self, project_id: str, group_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Revokes a group's access to a project."""
        return self._json(_REMOVE_PROJECT_GROUP, _c.encoded_path("/organization/projects/{}/groups/{}", project_id, group_id), None, None, include_response)

    @_t.overload
    def retrieve_project_hosted_tool_permissions(self, project_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectHostedToolPermissions200, _Errors]: ...
    @_t.overload
    def retrieve_project_hosted_tool_permissions(self, project_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectHostedToolPermissions200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_hosted_tool_permissions(self, project_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns hosted tool permissions for a project."""
        return self._json(_RETRIEVE_PROJECT_HOSTED_TOOL_PERMISSIONS, _c.encoded_path("/organization/projects/{}/hosted_tool_permissions", project_id), None, None, include_response)

    @_t.overload
    def update_project_hosted_tool_permissions(self, project_id: str, *, payload: _T.UpdateProjectHostedToolPermissionsRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateProjectHostedToolPermissions200, _Errors]: ...
    @_t.overload
    def update_project_hosted_tool_permissions(self, project_id: str, *, payload: _T.UpdateProjectHostedToolPermissionsRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateProjectHostedToolPermissions200, _HttpClientResponse], _Errors]: ...
    def update_project_hosted_tool_permissions(self, project_id: str, *, payload: _T.UpdateProjectHostedToolPermissionsRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates hosted tool permissions for a project."""
        return self._json(_UPDATE_PROJECT_HOSTED_TOOL_PERMISSIONS, _c.encoded_path("/organization/projects/{}/hosted_tool_permissions", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_project_model_permissions(self, project_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectModelPermissions200, _Errors]: ...
    @_t.overload
    def retrieve_project_model_permissions(self, project_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectModelPermissions200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_model_permissions(self, project_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns model permissions for a project."""
        return self._json(_RETRIEVE_PROJECT_MODEL_PERMISSIONS, _c.encoded_path("/organization/projects/{}/model_permissions", project_id), None, None, include_response)

    @_t.overload
    def update_project_model_permissions(self, project_id: str, *, payload: _T.UpdateProjectModelPermissionsRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateProjectModelPermissions200, _Errors]: ...
    @_t.overload
    def update_project_model_permissions(self, project_id: str, *, payload: _T.UpdateProjectModelPermissionsRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateProjectModelPermissions200, _HttpClientResponse], _Errors]: ...
    def update_project_model_permissions(self, project_id: str, *, payload: _T.UpdateProjectModelPermissionsRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates model permissions for a project."""
        return self._json(_UPDATE_PROJECT_MODEL_PERMISSIONS, _c.encoded_path("/organization/projects/{}/model_permissions", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_project_model_permissions(self, project_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteProjectModelPermissions200, _Errors]: ...
    @_t.overload
    def delete_project_model_permissions(self, project_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteProjectModelPermissions200, _HttpClientResponse], _Errors]: ...
    def delete_project_model_permissions(self, project_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes model permissions for a project."""
        return self._json(_DELETE_PROJECT_MODEL_PERMISSIONS, _c.encoded_path("/organization/projects/{}/model_permissions", project_id), None, None, include_response)

    @_t.overload
    def list_project_rate_limits(self, project_id: str, *, params: _T.ListProjectRateLimitsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjectRateLimits200, _Errors]: ...
    @_t.overload
    def list_project_rate_limits(self, project_id: str, *, params: _T.ListProjectRateLimitsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjectRateLimits200, _HttpClientResponse], _Errors]: ...
    def list_project_rate_limits(self, project_id: str, *, params: _T.ListProjectRateLimitsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns the rate limits per model for a project."""
        return self._json(_LIST_PROJECT_RATE_LIMITS, _c.encoded_path("/organization/projects/{}/rate_limits", project_id), params, None, include_response)

    @_t.overload
    def update_project_rate_limits(self, project_id: str, rate_limit_id: str, *, payload: _T.UpdateProjectRateLimitsRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateProjectRateLimits200, _Errors]: ...
    @_t.overload
    def update_project_rate_limits(self, project_id: str, rate_limit_id: str, *, payload: _T.UpdateProjectRateLimitsRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateProjectRateLimits200, _HttpClientResponse], _Errors]: ...
    def update_project_rate_limits(self, project_id: str, rate_limit_id: str, *, payload: _T.UpdateProjectRateLimitsRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates a project rate limit."""
        return self._json(_UPDATE_PROJECT_RATE_LIMITS, _c.encoded_path("/organization/projects/{}/rate_limits/{}", project_id, rate_limit_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def list_project_service_accounts(self, project_id: str, *, params: _T.ListProjectServiceAccountsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjectServiceAccounts200, _Errors]: ...
    @_t.overload
    def list_project_service_accounts(self, project_id: str, *, params: _T.ListProjectServiceAccountsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjectServiceAccounts200, _HttpClientResponse], _Errors]: ...
    def list_project_service_accounts(self, project_id: str, *, params: _T.ListProjectServiceAccountsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of service accounts in the project."""
        return self._json(_LIST_PROJECT_SERVICE_ACCOUNTS, _c.encoded_path("/organization/projects/{}/service_accounts", project_id), params, None, include_response)

    @_t.overload
    def create_project_service_account(self, project_id: str, *, payload: _T.CreateProjectServiceAccountRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateProjectServiceAccount200 | _T.CreateProjectServiceAccount201, _Errors]: ...
    @_t.overload
    def create_project_service_account(self, project_id: str, *, payload: _T.CreateProjectServiceAccountRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateProjectServiceAccount200 | _T.CreateProjectServiceAccount201, _HttpClientResponse], _Errors]: ...
    def create_project_service_account(self, project_id: str, *, payload: _T.CreateProjectServiceAccountRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a new service account in the project. By default, this also returns an unredacted API key for the service account."""
        return self._json(_CREATE_PROJECT_SERVICE_ACCOUNT, _c.encoded_path("/organization/projects/{}/service_accounts", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_project_service_account(self, project_id: str, service_account_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectServiceAccount200, _Errors]: ...
    @_t.overload
    def retrieve_project_service_account(self, project_id: str, service_account_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectServiceAccount200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_service_account(self, project_id: str, service_account_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a service account in the project."""
        return self._json(_RETRIEVE_PROJECT_SERVICE_ACCOUNT, _c.encoded_path("/organization/projects/{}/service_accounts/{}", project_id, service_account_id), None, None, include_response)

    @_t.overload
    def update_project_service_account(self, project_id: str, service_account_id: str, *, payload: _T.UpdateProjectServiceAccountRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateProjectServiceAccount200, _Errors]: ...
    @_t.overload
    def update_project_service_account(self, project_id: str, service_account_id: str, *, payload: _T.UpdateProjectServiceAccountRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateProjectServiceAccount200, _HttpClientResponse], _Errors]: ...
    def update_project_service_account(self, project_id: str, service_account_id: str, *, payload: _T.UpdateProjectServiceAccountRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates a service account in the project."""
        return self._json(_UPDATE_PROJECT_SERVICE_ACCOUNT, _c.encoded_path("/organization/projects/{}/service_accounts/{}", project_id, service_account_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_project_service_account(self, project_id: str, service_account_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteProjectServiceAccount200, _Errors]: ...
    @_t.overload
    def delete_project_service_account(self, project_id: str, service_account_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteProjectServiceAccount200, _HttpClientResponse], _Errors]: ...
    def delete_project_service_account(self, project_id: str, service_account_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a service account from the project.
        
        Returns confirmation of service account deletion, or an error if the project
        is archived (archived projects have no service accounts)."""
        return self._json(_DELETE_PROJECT_SERVICE_ACCOUNT, _c.encoded_path("/organization/projects/{}/service_accounts/{}", project_id, service_account_id), None, None, include_response)

    @_t.overload
    def list_project_spend_alerts(self, project_id: str, *, params: _T.ListProjectSpendAlertsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjectSpendAlerts200, _Errors]: ...
    @_t.overload
    def list_project_spend_alerts(self, project_id: str, *, params: _T.ListProjectSpendAlertsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjectSpendAlerts200, _HttpClientResponse], _Errors]: ...
    def list_project_spend_alerts(self, project_id: str, *, params: _T.ListProjectSpendAlertsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists project spend alerts."""
        return self._json(_LIST_PROJECT_SPEND_ALERTS, _c.encoded_path("/organization/projects/{}/spend_alerts", project_id), params, None, include_response)

    @_t.overload
    def create_project_spend_alert(self, project_id: str, *, payload: _T.CreateProjectSpendAlertRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateProjectSpendAlert200, _Errors]: ...
    @_t.overload
    def create_project_spend_alert(self, project_id: str, *, payload: _T.CreateProjectSpendAlertRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateProjectSpendAlert200, _HttpClientResponse], _Errors]: ...
    def create_project_spend_alert(self, project_id: str, *, payload: _T.CreateProjectSpendAlertRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a project spend alert."""
        return self._json(_CREATE_PROJECT_SPEND_ALERT, _c.encoded_path("/organization/projects/{}/spend_alerts", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_project_spend_alert(self, project_id: str, alert_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectSpendAlert200, _Errors]: ...
    @_t.overload
    def retrieve_project_spend_alert(self, project_id: str, alert_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectSpendAlert200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_spend_alert(self, project_id: str, alert_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a project spend alert."""
        return self._json(_RETRIEVE_PROJECT_SPEND_ALERT, _c.encoded_path("/organization/projects/{}/spend_alerts/{}", project_id, alert_id), None, None, include_response)

    @_t.overload
    def update_project_spend_alert(self, project_id: str, alert_id: str, *, payload: _T.UpdateProjectSpendAlertRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateProjectSpendAlert200, _Errors]: ...
    @_t.overload
    def update_project_spend_alert(self, project_id: str, alert_id: str, *, payload: _T.UpdateProjectSpendAlertRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateProjectSpendAlert200, _HttpClientResponse], _Errors]: ...
    def update_project_spend_alert(self, project_id: str, alert_id: str, *, payload: _T.UpdateProjectSpendAlertRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates a project spend alert."""
        return self._json(_UPDATE_PROJECT_SPEND_ALERT, _c.encoded_path("/organization/projects/{}/spend_alerts/{}", project_id, alert_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_project_spend_alert(self, project_id: str, alert_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteProjectSpendAlert200, _Errors]: ...
    @_t.overload
    def delete_project_spend_alert(self, project_id: str, alert_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteProjectSpendAlert200, _HttpClientResponse], _Errors]: ...
    def delete_project_spend_alert(self, project_id: str, alert_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a project spend alert."""
        return self._json(_DELETE_PROJECT_SPEND_ALERT, _c.encoded_path("/organization/projects/{}/spend_alerts/{}", project_id, alert_id), None, None, include_response)

    @_t.overload
    def list_project_users(self, project_id: str, *, params: _T.ListProjectUsersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjectUsers200, _Errors]: ...
    @_t.overload
    def list_project_users(self, project_id: str, *, params: _T.ListProjectUsersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjectUsers200, _HttpClientResponse], _Errors]: ...
    def list_project_users(self, project_id: str, *, params: _T.ListProjectUsersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of users in the project."""
        return self._json(_LIST_PROJECT_USERS, _c.encoded_path("/organization/projects/{}/users", project_id), params, None, include_response)

    @_t.overload
    def create_project_user(self, project_id: str, *, payload: _T.CreateProjectUserRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateProjectUser200 | _T.CreateProjectUser201, _Errors]: ...
    @_t.overload
    def create_project_user(self, project_id: str, *, payload: _T.CreateProjectUserRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateProjectUser200 | _T.CreateProjectUser201, _HttpClientResponse], _Errors]: ...
    def create_project_user(self, project_id: str, *, payload: _T.CreateProjectUserRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Adds a user to the project. Users must already be members of the organization to be added to a project."""
        return self._json(_CREATE_PROJECT_USER, _c.encoded_path("/organization/projects/{}/users", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_project_user(self, project_id: str, user_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectUser200, _Errors]: ...
    @_t.overload
    def retrieve_project_user(self, project_id: str, user_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectUser200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_user(self, project_id: str, user_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a user in the project."""
        return self._json(_RETRIEVE_PROJECT_USER, _c.encoded_path("/organization/projects/{}/users/{}", project_id, user_id), None, None, include_response)

    @_t.overload
    def modify_project_user(self, project_id: str, user_id: str, *, payload: _T.ModifyProjectUserRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ModifyProjectUser200, _Errors]: ...
    @_t.overload
    def modify_project_user(self, project_id: str, user_id: str, *, payload: _T.ModifyProjectUserRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ModifyProjectUser200, _HttpClientResponse], _Errors]: ...
    def modify_project_user(self, project_id: str, user_id: str, *, payload: _T.ModifyProjectUserRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Modifies a user's role in the project."""
        return self._json(_MODIFY_PROJECT_USER, _c.encoded_path("/organization/projects/{}/users/{}", project_id, user_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_project_user(self, project_id: str, user_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteProjectUser200, _Errors]: ...
    @_t.overload
    def delete_project_user(self, project_id: str, user_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteProjectUser200, _HttpClientResponse], _Errors]: ...
    def delete_project_user(self, project_id: str, user_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a user from the project.
        
        Returns confirmation of project user deletion, or an error if the project is
        archived (archived projects have no users)."""
        return self._json(_DELETE_PROJECT_USER, _c.encoded_path("/organization/projects/{}/users/{}", project_id, user_id), None, None, include_response)

    @_t.overload
    def list_roles(self, *, params: _T.ListRolesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListRoles200, _Errors]: ...
    @_t.overload
    def list_roles(self, *, params: _T.ListRolesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListRoles200, _HttpClientResponse], _Errors]: ...
    def list_roles(self, *, params: _T.ListRolesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the roles configured for the organization."""
        return self._json(_LIST_ROLES, "/organization/roles", params, None, include_response)

    @_t.overload
    def create_role(self, *, payload: _T.CreateRoleRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateRole200, _Errors]: ...
    @_t.overload
    def create_role(self, *, payload: _T.CreateRoleRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateRole200, _HttpClientResponse], _Errors]: ...
    def create_role(self, *, payload: _T.CreateRoleRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a custom role for the organization."""
        return self._json(_CREATE_ROLE, "/organization/roles", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_role(self, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveRole200, _Errors]: ...
    @_t.overload
    def retrieve_role(self, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveRole200, _HttpClientResponse], _Errors]: ...
    def retrieve_role(self, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves an organization role."""
        return self._json(_RETRIEVE_ROLE, _c.encoded_path("/organization/roles/{}", role_id), None, None, include_response)

    @_t.overload
    def update_role(self, role_id: str, *, payload: _T.UpdateRoleRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateRole200, _Errors]: ...
    @_t.overload
    def update_role(self, role_id: str, *, payload: _T.UpdateRoleRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateRole200, _HttpClientResponse], _Errors]: ...
    def update_role(self, role_id: str, *, payload: _T.UpdateRoleRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates an existing organization role."""
        return self._json(_UPDATE_ROLE, _c.encoded_path("/organization/roles/{}", role_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_role(self, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteRole200, _Errors]: ...
    @_t.overload
    def delete_role(self, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteRole200, _HttpClientResponse], _Errors]: ...
    def delete_role(self, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a custom role from the organization."""
        return self._json(_DELETE_ROLE, _c.encoded_path("/organization/roles/{}", role_id), None, None, include_response)

    @_t.overload
    def list_organization_spend_alerts(self, *, params: _T.ListOrganizationSpendAlertsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListOrganizationSpendAlerts200, _Errors]: ...
    @_t.overload
    def list_organization_spend_alerts(self, *, params: _T.ListOrganizationSpendAlertsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListOrganizationSpendAlerts200, _HttpClientResponse], _Errors]: ...
    def list_organization_spend_alerts(self, *, params: _T.ListOrganizationSpendAlertsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists organization spend alerts."""
        return self._json(_LIST_ORGANIZATION_SPEND_ALERTS, "/organization/spend_alerts", params, None, include_response)

    @_t.overload
    def create_organization_spend_alert(self, *, payload: _T.CreateOrganizationSpendAlertRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateOrganizationSpendAlert200, _Errors]: ...
    @_t.overload
    def create_organization_spend_alert(self, *, payload: _T.CreateOrganizationSpendAlertRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateOrganizationSpendAlert200, _HttpClientResponse], _Errors]: ...
    def create_organization_spend_alert(self, *, payload: _T.CreateOrganizationSpendAlertRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates an organization spend alert."""
        return self._json(_CREATE_ORGANIZATION_SPEND_ALERT, "/organization/spend_alerts", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_organization_spend_alert(self, alert_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveOrganizationSpendAlert200, _Errors]: ...
    @_t.overload
    def retrieve_organization_spend_alert(self, alert_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveOrganizationSpendAlert200, _HttpClientResponse], _Errors]: ...
    def retrieve_organization_spend_alert(self, alert_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves an organization spend alert."""
        return self._json(_RETRIEVE_ORGANIZATION_SPEND_ALERT, _c.encoded_path("/organization/spend_alerts/{}", alert_id), None, None, include_response)

    @_t.overload
    def update_organization_spend_alert(self, alert_id: str, *, payload: _T.UpdateOrganizationSpendAlertRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateOrganizationSpendAlert200, _Errors]: ...
    @_t.overload
    def update_organization_spend_alert(self, alert_id: str, *, payload: _T.UpdateOrganizationSpendAlertRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateOrganizationSpendAlert200, _HttpClientResponse], _Errors]: ...
    def update_organization_spend_alert(self, alert_id: str, *, payload: _T.UpdateOrganizationSpendAlertRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates an organization spend alert."""
        return self._json(_UPDATE_ORGANIZATION_SPEND_ALERT, _c.encoded_path("/organization/spend_alerts/{}", alert_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_organization_spend_alert(self, alert_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteOrganizationSpendAlert200, _Errors]: ...
    @_t.overload
    def delete_organization_spend_alert(self, alert_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteOrganizationSpendAlert200, _HttpClientResponse], _Errors]: ...
    def delete_organization_spend_alert(self, alert_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes an organization spend alert."""
        return self._json(_DELETE_ORGANIZATION_SPEND_ALERT, _c.encoded_path("/organization/spend_alerts/{}", alert_id), None, None, include_response)

    @_t.overload
    def usage_audio_speeches(self, *, params: _T.UsageAudioSpeechesParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageAudioSpeeches200, _Errors]: ...
    @_t.overload
    def usage_audio_speeches(self, *, params: _T.UsageAudioSpeechesParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageAudioSpeeches200, _HttpClientResponse], _Errors]: ...
    def usage_audio_speeches(self, *, params: _T.UsageAudioSpeechesParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get audio speeches usage details for the organization."""
        return self._json(_USAGE_AUDIO_SPEECHES, "/organization/usage/audio_speeches", params, None, include_response)

    @_t.overload
    def usage_audio_transcriptions(self, *, params: _T.UsageAudioTranscriptionsParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageAudioTranscriptions200, _Errors]: ...
    @_t.overload
    def usage_audio_transcriptions(self, *, params: _T.UsageAudioTranscriptionsParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageAudioTranscriptions200, _HttpClientResponse], _Errors]: ...
    def usage_audio_transcriptions(self, *, params: _T.UsageAudioTranscriptionsParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get audio transcriptions usage details for the organization."""
        return self._json(_USAGE_AUDIO_TRANSCRIPTIONS, "/organization/usage/audio_transcriptions", params, None, include_response)

    @_t.overload
    def usage_code_interpreter_sessions(self, *, params: _T.UsageCodeInterpreterSessionsParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageCodeInterpreterSessions200, _Errors]: ...
    @_t.overload
    def usage_code_interpreter_sessions(self, *, params: _T.UsageCodeInterpreterSessionsParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageCodeInterpreterSessions200, _HttpClientResponse], _Errors]: ...
    def usage_code_interpreter_sessions(self, *, params: _T.UsageCodeInterpreterSessionsParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get code interpreter sessions usage details for the organization."""
        return self._json(_USAGE_CODE_INTERPRETER_SESSIONS, "/organization/usage/code_interpreter_sessions", params, None, include_response)

    @_t.overload
    def usage_completions(self, *, params: _T.UsageCompletionsParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageCompletions200, _Errors]: ...
    @_t.overload
    def usage_completions(self, *, params: _T.UsageCompletionsParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageCompletions200, _HttpClientResponse], _Errors]: ...
    def usage_completions(self, *, params: _T.UsageCompletionsParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get completions usage details for the organization."""
        return self._json(_USAGE_COMPLETIONS, "/organization/usage/completions", params, None, include_response)

    @_t.overload
    def usage_embeddings(self, *, params: _T.UsageEmbeddingsParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageEmbeddings200, _Errors]: ...
    @_t.overload
    def usage_embeddings(self, *, params: _T.UsageEmbeddingsParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageEmbeddings200, _HttpClientResponse], _Errors]: ...
    def usage_embeddings(self, *, params: _T.UsageEmbeddingsParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get embeddings usage details for the organization."""
        return self._json(_USAGE_EMBEDDINGS, "/organization/usage/embeddings", params, None, include_response)

    @_t.overload
    def usage_file_search_calls(self, *, params: _T.UsageFileSearchCallsParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageFileSearchCalls200, _Errors]: ...
    @_t.overload
    def usage_file_search_calls(self, *, params: _T.UsageFileSearchCallsParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageFileSearchCalls200, _HttpClientResponse], _Errors]: ...
    def usage_file_search_calls(self, *, params: _T.UsageFileSearchCallsParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get file search calls usage details for the organization."""
        return self._json(_USAGE_FILE_SEARCH_CALLS, "/organization/usage/file_search_calls", params, None, include_response)

    @_t.overload
    def usage_images(self, *, params: _T.UsageImagesParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageImages200, _Errors]: ...
    @_t.overload
    def usage_images(self, *, params: _T.UsageImagesParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageImages200, _HttpClientResponse], _Errors]: ...
    def usage_images(self, *, params: _T.UsageImagesParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get images usage details for the organization."""
        return self._json(_USAGE_IMAGES, "/organization/usage/images", params, None, include_response)

    @_t.overload
    def usage_moderations(self, *, params: _T.UsageModerationsParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageModerations200, _Errors]: ...
    @_t.overload
    def usage_moderations(self, *, params: _T.UsageModerationsParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageModerations200, _HttpClientResponse], _Errors]: ...
    def usage_moderations(self, *, params: _T.UsageModerationsParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get moderations usage details for the organization."""
        return self._json(_USAGE_MODERATIONS, "/organization/usage/moderations", params, None, include_response)

    @_t.overload
    def usage_vector_stores(self, *, params: _T.UsageVectorStoresParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageVectorStores200, _Errors]: ...
    @_t.overload
    def usage_vector_stores(self, *, params: _T.UsageVectorStoresParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageVectorStores200, _HttpClientResponse], _Errors]: ...
    def usage_vector_stores(self, *, params: _T.UsageVectorStoresParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get vector stores usage details for the organization."""
        return self._json(_USAGE_VECTOR_STORES, "/organization/usage/vector_stores", params, None, include_response)

    @_t.overload
    def usage_web_search_calls(self, *, params: _T.UsageWebSearchCallsParams, include_response: _t.Literal[False] = False) -> _Effect[_T.UsageWebSearchCalls200, _Errors]: ...
    @_t.overload
    def usage_web_search_calls(self, *, params: _T.UsageWebSearchCallsParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UsageWebSearchCalls200, _HttpClientResponse], _Errors]: ...
    def usage_web_search_calls(self, *, params: _T.UsageWebSearchCallsParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get web search calls usage details for the organization."""
        return self._json(_USAGE_WEB_SEARCH_CALLS, "/organization/usage/web_search_calls", params, None, include_response)

    @_t.overload
    def list_users(self, *, params: _T.ListUsersParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListUsers200, _Errors]: ...
    @_t.overload
    def list_users(self, *, params: _T.ListUsersParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListUsers200, _HttpClientResponse], _Errors]: ...
    def list_users(self, *, params: _T.ListUsersParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists all of the users in the organization."""
        return self._json(_LIST_USERS, "/organization/users", params, None, include_response)

    @_t.overload
    def retrieve_user(self, user_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveUser200, _Errors]: ...
    @_t.overload
    def retrieve_user(self, user_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveUser200, _HttpClientResponse], _Errors]: ...
    def retrieve_user(self, user_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a user by their identifier."""
        return self._json(_RETRIEVE_USER, _c.encoded_path("/organization/users/{}", user_id), None, None, include_response)

    @_t.overload
    def modify_user(self, user_id: str, *, payload: _T.ModifyUserRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ModifyUser200, _Errors]: ...
    @_t.overload
    def modify_user(self, user_id: str, *, payload: _T.ModifyUserRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ModifyUser200, _HttpClientResponse], _Errors]: ...
    def modify_user(self, user_id: str, *, payload: _T.ModifyUserRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Modifies a user's role in the organization."""
        return self._json(_MODIFY_USER, _c.encoded_path("/organization/users/{}", user_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_user(self, user_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteUser200, _Errors]: ...
    @_t.overload
    def delete_user(self, user_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteUser200, _HttpClientResponse], _Errors]: ...
    def delete_user(self, user_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a user from the organization."""
        return self._json(_DELETE_USER, _c.encoded_path("/organization/users/{}", user_id), None, None, include_response)

    @_t.overload
    def list_user_role_assignments(self, user_id: str, *, params: _T.ListUserRoleAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListUserRoleAssignments200, _Errors]: ...
    @_t.overload
    def list_user_role_assignments(self, user_id: str, *, params: _T.ListUserRoleAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListUserRoleAssignments200, _HttpClientResponse], _Errors]: ...
    def list_user_role_assignments(self, user_id: str, *, params: _T.ListUserRoleAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the organization roles assigned to a user within the organization."""
        return self._json(_LIST_USER_ROLE_ASSIGNMENTS, _c.encoded_path("/organization/users/{}/roles", user_id), params, None, include_response)

    @_t.overload
    def assign_user_role(self, user_id: str, *, payload: _T.AssignUserRoleRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.AssignUserRole200, _Errors]: ...
    @_t.overload
    def assign_user_role(self, user_id: str, *, payload: _T.AssignUserRoleRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AssignUserRole200, _HttpClientResponse], _Errors]: ...
    def assign_user_role(self, user_id: str, *, payload: _T.AssignUserRoleRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Assigns an organization role to a user within the organization."""
        return self._json(_ASSIGN_USER_ROLE, _c.encoded_path("/organization/users/{}/roles", user_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_user_role(self, user_id: str, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveUserRole200, _Errors]: ...
    @_t.overload
    def retrieve_user_role(self, user_id: str, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveUserRole200, _HttpClientResponse], _Errors]: ...
    def retrieve_user_role(self, user_id: str, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves an organization role assigned to a user."""
        return self._json(_RETRIEVE_USER_ROLE, _c.encoded_path("/organization/users/{}/roles/{}", user_id, role_id), None, None, include_response)

    @_t.overload
    def unassign_user_role(self, user_id: str, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.UnassignUserRole200, _Errors]: ...
    @_t.overload
    def unassign_user_role(self, user_id: str, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UnassignUserRole200, _HttpClientResponse], _Errors]: ...
    def unassign_user_role(self, user_id: str, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Unassigns an organization role from a user within the organization."""
        return self._json(_UNASSIGN_USER_ROLE, _c.encoded_path("/organization/users/{}/roles/{}", user_id, role_id), None, None, include_response)

    @_t.overload
    def list_project_group_role_assignments(self, project_id: str, group_id: str, *, params: _T.ListProjectGroupRoleAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjectGroupRoleAssignments200, _Errors]: ...
    @_t.overload
    def list_project_group_role_assignments(self, project_id: str, group_id: str, *, params: _T.ListProjectGroupRoleAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjectGroupRoleAssignments200, _HttpClientResponse], _Errors]: ...
    def list_project_group_role_assignments(self, project_id: str, group_id: str, *, params: _T.ListProjectGroupRoleAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the project roles assigned to a group within a project."""
        return self._json(_LIST_PROJECT_GROUP_ROLE_ASSIGNMENTS, _c.encoded_path("/projects/{}/groups/{}/roles", project_id, group_id), params, None, include_response)

    @_t.overload
    def assign_project_group_role(self, project_id: str, group_id: str, *, payload: _T.AssignProjectGroupRoleRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.AssignProjectGroupRole200, _Errors]: ...
    @_t.overload
    def assign_project_group_role(self, project_id: str, group_id: str, *, payload: _T.AssignProjectGroupRoleRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AssignProjectGroupRole200, _HttpClientResponse], _Errors]: ...
    def assign_project_group_role(self, project_id: str, group_id: str, *, payload: _T.AssignProjectGroupRoleRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Assigns a project role to a group within a project."""
        return self._json(_ASSIGN_PROJECT_GROUP_ROLE, _c.encoded_path("/projects/{}/groups/{}/roles", project_id, group_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_project_group_role(self, project_id: str, group_id: str, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectGroupRole200, _Errors]: ...
    @_t.overload
    def retrieve_project_group_role(self, project_id: str, group_id: str, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectGroupRole200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_group_role(self, project_id: str, group_id: str, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a project role assigned to a group."""
        return self._json(_RETRIEVE_PROJECT_GROUP_ROLE, _c.encoded_path("/projects/{}/groups/{}/roles/{}", project_id, group_id, role_id), None, None, include_response)

    @_t.overload
    def unassign_project_group_role(self, project_id: str, group_id: str, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.UnassignProjectGroupRole200, _Errors]: ...
    @_t.overload
    def unassign_project_group_role(self, project_id: str, group_id: str, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UnassignProjectGroupRole200, _HttpClientResponse], _Errors]: ...
    def unassign_project_group_role(self, project_id: str, group_id: str, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Unassigns a project role from a group within a project."""
        return self._json(_UNASSIGN_PROJECT_GROUP_ROLE, _c.encoded_path("/projects/{}/groups/{}/roles/{}", project_id, group_id, role_id), None, None, include_response)

    @_t.overload
    def list_project_roles(self, project_id: str, *, params: _T.ListProjectRolesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjectRoles200, _Errors]: ...
    @_t.overload
    def list_project_roles(self, project_id: str, *, params: _T.ListProjectRolesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjectRoles200, _HttpClientResponse], _Errors]: ...
    def list_project_roles(self, project_id: str, *, params: _T.ListProjectRolesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the roles configured for a project."""
        return self._json(_LIST_PROJECT_ROLES, _c.encoded_path("/projects/{}/roles", project_id), params, None, include_response)

    @_t.overload
    def create_project_role(self, project_id: str, *, payload: _T.CreateProjectRoleRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateProjectRole200, _Errors]: ...
    @_t.overload
    def create_project_role(self, project_id: str, *, payload: _T.CreateProjectRoleRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateProjectRole200, _HttpClientResponse], _Errors]: ...
    def create_project_role(self, project_id: str, *, payload: _T.CreateProjectRoleRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a custom role for a project."""
        return self._json(_CREATE_PROJECT_ROLE, _c.encoded_path("/projects/{}/roles", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_project_role(self, project_id: str, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectRole200, _Errors]: ...
    @_t.overload
    def retrieve_project_role(self, project_id: str, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectRole200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_role(self, project_id: str, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a project role."""
        return self._json(_RETRIEVE_PROJECT_ROLE, _c.encoded_path("/projects/{}/roles/{}", project_id, role_id), None, None, include_response)

    @_t.overload
    def update_project_role(self, project_id: str, role_id: str, *, payload: _T.UpdateProjectRoleRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateProjectRole200, _Errors]: ...
    @_t.overload
    def update_project_role(self, project_id: str, role_id: str, *, payload: _T.UpdateProjectRoleRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateProjectRole200, _HttpClientResponse], _Errors]: ...
    def update_project_role(self, project_id: str, role_id: str, *, payload: _T.UpdateProjectRoleRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates an existing project role."""
        return self._json(_UPDATE_PROJECT_ROLE, _c.encoded_path("/projects/{}/roles/{}", project_id, role_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_project_role(self, project_id: str, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteProjectRole200, _Errors]: ...
    @_t.overload
    def delete_project_role(self, project_id: str, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteProjectRole200, _HttpClientResponse], _Errors]: ...
    def delete_project_role(self, project_id: str, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a custom role from a project."""
        return self._json(_DELETE_PROJECT_ROLE, _c.encoded_path("/projects/{}/roles/{}", project_id, role_id), None, None, include_response)

    @_t.overload
    def list_project_user_role_assignments(self, project_id: str, user_id: str, *, params: _T.ListProjectUserRoleAssignmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListProjectUserRoleAssignments200, _Errors]: ...
    @_t.overload
    def list_project_user_role_assignments(self, project_id: str, user_id: str, *, params: _T.ListProjectUserRoleAssignmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListProjectUserRoleAssignments200, _HttpClientResponse], _Errors]: ...
    def list_project_user_role_assignments(self, project_id: str, user_id: str, *, params: _T.ListProjectUserRoleAssignmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists the project roles assigned to a user within a project."""
        return self._json(_LIST_PROJECT_USER_ROLE_ASSIGNMENTS, _c.encoded_path("/projects/{}/users/{}/roles", project_id, user_id), params, None, include_response)

    @_t.overload
    def assign_project_user_role(self, project_id: str, user_id: str, *, payload: _T.AssignProjectUserRoleRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.AssignProjectUserRole200, _Errors]: ...
    @_t.overload
    def assign_project_user_role(self, project_id: str, user_id: str, *, payload: _T.AssignProjectUserRoleRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AssignProjectUserRole200, _HttpClientResponse], _Errors]: ...
    def assign_project_user_role(self, project_id: str, user_id: str, *, payload: _T.AssignProjectUserRoleRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Assigns a project role to a user within a project."""
        return self._json(_ASSIGN_PROJECT_USER_ROLE, _c.encoded_path("/projects/{}/users/{}/roles", project_id, user_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_project_user_role(self, project_id: str, user_id: str, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveProjectUserRole200, _Errors]: ...
    @_t.overload
    def retrieve_project_user_role(self, project_id: str, user_id: str, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveProjectUserRole200, _HttpClientResponse], _Errors]: ...
    def retrieve_project_user_role(self, project_id: str, user_id: str, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a project role assigned to a user."""
        return self._json(_RETRIEVE_PROJECT_USER_ROLE, _c.encoded_path("/projects/{}/users/{}/roles/{}", project_id, user_id, role_id), None, None, include_response)

    @_t.overload
    def unassign_project_user_role(self, project_id: str, user_id: str, role_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.UnassignProjectUserRole200, _Errors]: ...
    @_t.overload
    def unassign_project_user_role(self, project_id: str, user_id: str, role_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UnassignProjectUserRole200, _HttpClientResponse], _Errors]: ...
    def unassign_project_user_role(self, project_id: str, user_id: str, role_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Unassigns a project role from a user within a project."""
        return self._json(_UNASSIGN_PROJECT_USER_ROLE, _c.encoded_path("/projects/{}/users/{}/roles/{}", project_id, user_id, role_id), None, None, include_response)

    @_t.overload
    def create_realtime_call(self, *, payload: _T.CreateRealtimeCallRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[None, _PlainErrors]: ...
    @_t.overload
    def create_realtime_call(self, *, payload: _T.CreateRealtimeCallRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _PlainErrors]: ...
    def create_realtime_call(self, *, payload: _T.CreateRealtimeCallRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _PlainErrors]:
        """Create a new Realtime API call over WebRTC and receive the SDP answer needed
        to complete the peer connection."""
        return self._json(_CREATE_REALTIME_CALL, "/realtime/calls", None, _c.form_body(payload), include_response)

    @_t.overload
    def accept_realtime_call(self, call_id: str, *, payload: _T.AcceptRealtimeCallRequestJson, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def accept_realtime_call(self, call_id: str, *, payload: _T.AcceptRealtimeCallRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def accept_realtime_call(self, call_id: str, *, payload: _T.AcceptRealtimeCallRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Accept an incoming SIP call and configure the realtime session that will
        handle it."""
        return self._json(_ACCEPT_REALTIME_CALL, _c.encoded_path("/realtime/calls/{}/accept", call_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def hangup_realtime_call(self, call_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def hangup_realtime_call(self, call_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def hangup_realtime_call(self, call_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """End an active Realtime API call, whether it was initiated over SIP or
        WebRTC."""
        return self._json(_HANGUP_REALTIME_CALL, _c.encoded_path("/realtime/calls/{}/hangup", call_id), None, None, include_response)

    @_t.overload
    def refer_realtime_call(self, call_id: str, *, payload: _T.ReferRealtimeCallRequestJson, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def refer_realtime_call(self, call_id: str, *, payload: _T.ReferRealtimeCallRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def refer_realtime_call(self, call_id: str, *, payload: _T.ReferRealtimeCallRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Transfer an active SIP call to a new destination using the SIP REFER verb."""
        return self._json(_REFER_REALTIME_CALL, _c.encoded_path("/realtime/calls/{}/refer", call_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def reject_realtime_call(self, call_id: str, *, payload: _T.RejectRealtimeCallRequestJson, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def reject_realtime_call(self, call_id: str, *, payload: _T.RejectRealtimeCallRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def reject_realtime_call(self, call_id: str, *, payload: _T.RejectRealtimeCallRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Decline an incoming SIP call by returning a SIP status code to the caller."""
        return self._json(_REJECT_REALTIME_CALL, _c.encoded_path("/realtime/calls/{}/reject", call_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def create_realtime_client_secret(self, *, payload: _T.CreateRealtimeClientSecretRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateRealtimeClientSecret200, _Errors]: ...
    @_t.overload
    def create_realtime_client_secret(self, *, payload: _T.CreateRealtimeClientSecretRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateRealtimeClientSecret200, _HttpClientResponse], _Errors]: ...
    def create_realtime_client_secret(self, *, payload: _T.CreateRealtimeClientSecretRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a Realtime client secret with an associated session configuration.
        
        Client secrets are short-lived tokens that can be passed to a client app,
        such as a web frontend or mobile client, which grants access to the Realtime API without
        leaking your main API key. You can configure a custom TTL for each client secret.
        
        You can also attach session configuration options to the client secret, which will be
        applied to any sessions created using that client secret, but these can also be overridden
        by the client connection.
        
        [Learn more about authentication with client secrets over WebRTC](https://developers.openai.com/api/docs/guides/realtime-webrtc).
        
        Returns the created client secret and the effective session object. The client secret is a string that looks like `ek_1234`."""
        return self._json(_CREATE_REALTIME_CLIENT_SECRET, "/realtime/client_secrets", None, _c.json_body(payload), include_response)

    @_t.overload
    def create_realtime_session(self, *, payload: _T.CreateRealtimeSessionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateRealtimeSession200, _PlainErrors]: ...
    @_t.overload
    def create_realtime_session(self, *, payload: _T.CreateRealtimeSessionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateRealtimeSession200, _HttpClientResponse], _PlainErrors]: ...
    def create_realtime_session(self, *, payload: _T.CreateRealtimeSessionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _PlainErrors]:
        """Create an ephemeral API token for use in client-side applications with the
        Realtime API. Can be configured with the same session parameters as the
        `session.update` client event.
        
        It responds with a session object, plus a `client_secret` key which contains
        a usable ephemeral API token that can be used to authenticate browser clients
        for the Realtime API.
        
        Returns the created Realtime session object, plus an ephemeral key."""
        return self._json(_CREATE_REALTIME_SESSION, "/realtime/sessions", None, _c.json_body(payload), include_response)

    @_t.overload
    def create_realtime_transcription_session(self, *, payload: _T.CreateRealtimeTranscriptionSessionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateRealtimeTranscriptionSession200, _PlainErrors]: ...
    @_t.overload
    def create_realtime_transcription_session(self, *, payload: _T.CreateRealtimeTranscriptionSessionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateRealtimeTranscriptionSession200, _HttpClientResponse], _PlainErrors]: ...
    def create_realtime_transcription_session(self, *, payload: _T.CreateRealtimeTranscriptionSessionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _PlainErrors]:
        """Create an ephemeral API token for use in client-side applications with the
        Realtime API specifically for realtime transcriptions.
        Can be configured with the same session parameters as the `transcription_session.update` client event.
        
        It responds with a session object, plus a `client_secret` key which contains
        a usable ephemeral API token that can be used to authenticate browser clients
        for the Realtime API.
        
        Returns the created Realtime transcription session object, plus an ephemeral key."""
        return self._json(_CREATE_REALTIME_TRANSCRIPTION_SESSION, "/realtime/transcription_sessions", None, _c.json_body(payload), include_response)

    @_t.overload
    def create_realtime_translation_client_secret(self, *, payload: _T.CreateRealtimeTranslationClientSecretRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateRealtimeTranslationClientSecret200, _Errors]: ...
    @_t.overload
    def create_realtime_translation_client_secret(self, *, payload: _T.CreateRealtimeTranslationClientSecretRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateRealtimeTranslationClientSecret200, _HttpClientResponse], _Errors]: ...
    def create_realtime_translation_client_secret(self, *, payload: _T.CreateRealtimeTranslationClientSecretRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a Realtime translation client secret with an associated translation session configuration.
        
        Client secrets are short-lived tokens that can be passed to a client app,
        such as a web frontend or mobile client, which grants access to the Realtime
        Translation API without leaking your main API key. You can configure a custom
        TTL for each client secret.
        
        Returns the created client secret and the effective translation session object.
        The client secret is a string that looks like `ek_1234`."""
        return self._json(_CREATE_REALTIME_TRANSLATION_CLIENT_SECRET, "/realtime/translations/client_secrets", None, _c.json_body(payload), include_response)

    @_t.overload
    def create_response(self, *, payload: _T.CreateResponseRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateResponse200, _Errors]: ...
    @_t.overload
    def create_response(self, *, payload: _T.CreateResponseRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateResponse200, _HttpClientResponse], _Errors]: ...
    def create_response(self, *, payload: _T.CreateResponseRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a model response. Provide [text](https://developers.openai.com/api/docs/guides/text) or
        [image](https://developers.openai.com/api/docs/guides/images-vision) inputs to generate [text](https://developers.openai.com/api/docs/guides/text)
        or [JSON](https://developers.openai.com/api/docs/guides/structured-outputs) outputs. Have the model call
        your own [custom code](https://developers.openai.com/api/docs/guides/function-calling) or use built-in
        [tools](https://developers.openai.com/api/docs/guides/tools) like [web search](https://developers.openai.com/api/docs/guides/tools-web-search)
        or [file search](https://developers.openai.com/api/docs/guides/tools-file-search) to use your own data
        as input for the model's response."""
        return self._json(_CREATE_RESPONSE, "/responses", None, _c.json_body(payload), include_response)

    def create_response_sse(self, *, payload: _T.CreateResponseRequestJson) -> _Stream[_sse.DataEvent[_T.CreateResponse200Sse], _SseErrors]:
        """Creates a model response. Provide [text](https://developers.openai.com/api/docs/guides/text) or
        [image](https://developers.openai.com/api/docs/guides/images-vision) inputs to generate [text](https://developers.openai.com/api/docs/guides/text)
        or [JSON](https://developers.openai.com/api/docs/guides/structured-outputs) outputs. Have the model call
        your own [custom code](https://developers.openai.com/api/docs/guides/function-calling) or use built-in
        [tools](https://developers.openai.com/api/docs/guides/tools) like [web search](https://developers.openai.com/api/docs/guides/tools-web-search)
        or [file search](https://developers.openai.com/api/docs/guides/tools-file-search) to use your own data
        as input for the model's response."""
        return self._sse(_CREATE_RESPONSE_SSE, "/responses", None, _c.json_body(payload), CreateResponse200Sse)

    @_t.overload
    def get_response(self, response_id: str, *, params: _T.GetResponseParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetResponse200, _Errors]: ...
    @_t.overload
    def get_response(self, response_id: str, *, params: _T.GetResponseParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetResponse200, _HttpClientResponse], _Errors]: ...
    def get_response(self, response_id: str, *, params: _T.GetResponseParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a model response with the given ID."""
        return self._json(_GET_RESPONSE, _c.encoded_path("/responses/{}", response_id), params, None, include_response)

    @_t.overload
    def delete_response(self, response_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteResponse200, _Errors]: ...
    @_t.overload
    def delete_response(self, response_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteResponse200, _HttpClientResponse], _Errors]: ...
    def delete_response(self, response_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a model response with the given ID."""
        return self._json(_DELETE_RESPONSE, _c.encoded_path("/responses/{}", response_id), None, None, include_response)

    @_t.overload
    def cancel_response(self, response_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.CancelResponse200, _Errors]: ...
    @_t.overload
    def cancel_response(self, response_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CancelResponse200, _HttpClientResponse], _Errors]: ...
    def cancel_response(self, response_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Cancels a model response with the given ID. Only responses created with
        the `background` parameter set to `true` can be cancelled.
        [Learn more](https://developers.openai.com/api/docs/guides/background)."""
        return self._json(_CANCEL_RESPONSE, _c.encoded_path("/responses/{}/cancel", response_id), None, None, include_response)

    @_t.overload
    def list_input_items(self, response_id: str, *, params: _T.ListInputItemsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListInputItems200, _Errors]: ...
    @_t.overload
    def list_input_items(self, response_id: str, *, params: _T.ListInputItemsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListInputItems200, _HttpClientResponse], _Errors]: ...
    def list_input_items(self, response_id: str, *, params: _T.ListInputItemsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of input items for a given response."""
        return self._json(_LIST_INPUT_ITEMS, _c.encoded_path("/responses/{}/input_items", response_id), params, None, include_response)

    @_t.overload
    def create_thread(self, *, payload: _T.CreateThreadRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateThread200, _Errors]: ...
    @_t.overload
    def create_thread(self, *, payload: _T.CreateThreadRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateThread200, _HttpClientResponse], _Errors]: ...
    def create_thread(self, *, payload: _T.CreateThreadRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a thread."""
        return self._json(_CREATE_THREAD, "/threads", None, _c.json_body(payload), include_response)

    @_t.overload
    def create_thread_and_run(self, *, payload: _T.CreateThreadAndRunRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateThreadAndRun200, _Errors]: ...
    @_t.overload
    def create_thread_and_run(self, *, payload: _T.CreateThreadAndRunRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateThreadAndRun200, _HttpClientResponse], _Errors]: ...
    def create_thread_and_run(self, *, payload: _T.CreateThreadAndRunRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a thread and run it in one request."""
        return self._json(_CREATE_THREAD_AND_RUN, "/threads/runs", None, _c.json_body(payload), include_response)

    def create_thread_and_run_sse(self, *, payload: _T.CreateThreadAndRunRequestJson) -> _Stream[_sse.DataEvent[_T.CreateThreadAndRun200Sse], _SseErrors]:
        """Create a thread and run it in one request."""
        return self._sse(_CREATE_THREAD_AND_RUN_SSE, "/threads/runs", None, _c.json_body(payload), CreateThreadAndRun200Sse)

    @_t.overload
    def get_thread(self, thread_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetThread200, _Errors]: ...
    @_t.overload
    def get_thread(self, thread_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetThread200, _HttpClientResponse], _Errors]: ...
    def get_thread(self, thread_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a thread."""
        return self._json(_GET_THREAD, _c.encoded_path("/threads/{}", thread_id), None, None, include_response)

    @_t.overload
    def modify_thread(self, thread_id: str, *, payload: _T.ModifyThreadRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ModifyThread200, _Errors]: ...
    @_t.overload
    def modify_thread(self, thread_id: str, *, payload: _T.ModifyThreadRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ModifyThread200, _HttpClientResponse], _Errors]: ...
    def modify_thread(self, thread_id: str, *, payload: _T.ModifyThreadRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Modifies a thread."""
        return self._json(_MODIFY_THREAD, _c.encoded_path("/threads/{}", thread_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_thread(self, thread_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteThread200, _Errors]: ...
    @_t.overload
    def delete_thread(self, thread_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteThread200, _HttpClientResponse], _Errors]: ...
    def delete_thread(self, thread_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a thread."""
        return self._json(_DELETE_THREAD, _c.encoded_path("/threads/{}", thread_id), None, None, include_response)

    @_t.overload
    def list_messages(self, thread_id: str, *, params: _T.ListMessagesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListMessages200, _Errors]: ...
    @_t.overload
    def list_messages(self, thread_id: str, *, params: _T.ListMessagesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListMessages200, _HttpClientResponse], _Errors]: ...
    def list_messages(self, thread_id: str, *, params: _T.ListMessagesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of messages for a given thread."""
        return self._json(_LIST_MESSAGES, _c.encoded_path("/threads/{}/messages", thread_id), params, None, include_response)

    @_t.overload
    def create_message(self, thread_id: str, *, payload: _T.CreateMessageRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateMessage200, _Errors]: ...
    @_t.overload
    def create_message(self, thread_id: str, *, payload: _T.CreateMessageRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateMessage200, _HttpClientResponse], _Errors]: ...
    def create_message(self, thread_id: str, *, payload: _T.CreateMessageRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a message."""
        return self._json(_CREATE_MESSAGE, _c.encoded_path("/threads/{}/messages", thread_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def get_message(self, thread_id: str, message_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetMessage200, _Errors]: ...
    @_t.overload
    def get_message(self, thread_id: str, message_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetMessage200, _HttpClientResponse], _Errors]: ...
    def get_message(self, thread_id: str, message_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieve a message."""
        return self._json(_GET_MESSAGE, _c.encoded_path("/threads/{}/messages/{}", thread_id, message_id), None, None, include_response)

    @_t.overload
    def modify_message(self, thread_id: str, message_id: str, *, payload: _T.ModifyMessageRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ModifyMessage200, _Errors]: ...
    @_t.overload
    def modify_message(self, thread_id: str, message_id: str, *, payload: _T.ModifyMessageRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ModifyMessage200, _HttpClientResponse], _Errors]: ...
    def modify_message(self, thread_id: str, message_id: str, *, payload: _T.ModifyMessageRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Modifies a message."""
        return self._json(_MODIFY_MESSAGE, _c.encoded_path("/threads/{}/messages/{}", thread_id, message_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_message(self, thread_id: str, message_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteMessage200, _Errors]: ...
    @_t.overload
    def delete_message(self, thread_id: str, message_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteMessage200, _HttpClientResponse], _Errors]: ...
    def delete_message(self, thread_id: str, message_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a message."""
        return self._json(_DELETE_MESSAGE, _c.encoded_path("/threads/{}/messages/{}", thread_id, message_id), None, None, include_response)

    @_t.overload
    def list_runs(self, thread_id: str, *, params: _T.ListRunsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListRuns200, _Errors]: ...
    @_t.overload
    def list_runs(self, thread_id: str, *, params: _T.ListRunsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListRuns200, _HttpClientResponse], _Errors]: ...
    def list_runs(self, thread_id: str, *, params: _T.ListRunsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of runs belonging to a thread."""
        return self._json(_LIST_RUNS, _c.encoded_path("/threads/{}/runs", thread_id), params, None, include_response)

    @_t.overload
    def create_run(self, thread_id: str, *, payload: _T.CreateRunRequestJson, params: _T.CreateRunParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateRun200, _Errors]: ...
    @_t.overload
    def create_run(self, thread_id: str, *, payload: _T.CreateRunRequestJson, params: _T.CreateRunParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateRun200, _HttpClientResponse], _Errors]: ...
    def create_run(self, thread_id: str, *, payload: _T.CreateRunRequestJson, params: _T.CreateRunParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a run."""
        return self._json(_CREATE_RUN, _c.encoded_path("/threads/{}/runs", thread_id), params, _c.json_body(payload), include_response)

    def create_run_sse(self, thread_id: str, *, payload: _T.CreateRunRequestJson, params: _T.CreateRunParams | None = None) -> _Stream[_sse.DataEvent[_T.CreateRun200Sse], _SseErrors]:
        """Create a run."""
        return self._sse(_CREATE_RUN_SSE, _c.encoded_path("/threads/{}/runs", thread_id), params, _c.json_body(payload), CreateRun200Sse)

    @_t.overload
    def get_run(self, thread_id: str, run_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetRun200, _Errors]: ...
    @_t.overload
    def get_run(self, thread_id: str, run_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetRun200, _HttpClientResponse], _Errors]: ...
    def get_run(self, thread_id: str, run_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a run."""
        return self._json(_GET_RUN, _c.encoded_path("/threads/{}/runs/{}", thread_id, run_id), None, None, include_response)

    @_t.overload
    def modify_run(self, thread_id: str, run_id: str, *, payload: _T.ModifyRunRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ModifyRun200, _Errors]: ...
    @_t.overload
    def modify_run(self, thread_id: str, run_id: str, *, payload: _T.ModifyRunRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ModifyRun200, _HttpClientResponse], _Errors]: ...
    def modify_run(self, thread_id: str, run_id: str, *, payload: _T.ModifyRunRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Modifies a run."""
        return self._json(_MODIFY_RUN, _c.encoded_path("/threads/{}/runs/{}", thread_id, run_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def cancel_run(self, thread_id: str, run_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.CancelRun200, _Errors]: ...
    @_t.overload
    def cancel_run(self, thread_id: str, run_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CancelRun200, _HttpClientResponse], _Errors]: ...
    def cancel_run(self, thread_id: str, run_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Cancels a run that is `in_progress`."""
        return self._json(_CANCEL_RUN, _c.encoded_path("/threads/{}/runs/{}/cancel", thread_id, run_id), None, None, include_response)

    @_t.overload
    def list_run_steps(self, thread_id: str, run_id: str, *, params: _T.ListRunStepsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListRunSteps200, _Errors]: ...
    @_t.overload
    def list_run_steps(self, thread_id: str, run_id: str, *, params: _T.ListRunStepsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListRunSteps200, _HttpClientResponse], _Errors]: ...
    def list_run_steps(self, thread_id: str, run_id: str, *, params: _T.ListRunStepsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of run steps belonging to a run."""
        return self._json(_LIST_RUN_STEPS, _c.encoded_path("/threads/{}/runs/{}/steps", thread_id, run_id), params, None, include_response)

    @_t.overload
    def get_run_step(self, thread_id: str, run_id: str, step_id: str, *, params: _T.GetRunStepParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.GetRunStep200, _Errors]: ...
    @_t.overload
    def get_run_step(self, thread_id: str, run_id: str, step_id: str, *, params: _T.GetRunStepParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetRunStep200, _HttpClientResponse], _Errors]: ...
    def get_run_step(self, thread_id: str, run_id: str, step_id: str, *, params: _T.GetRunStepParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a run step."""
        return self._json(_GET_RUN_STEP, _c.encoded_path("/threads/{}/runs/{}/steps/{}", thread_id, run_id, step_id), params, None, include_response)

    @_t.overload
    def submit_tool_ouputs_to_run(self, thread_id: str, run_id: str, *, payload: _T.SubmitToolOuputsToRunRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.SubmitToolOuputsToRun200, _Errors]: ...
    @_t.overload
    def submit_tool_ouputs_to_run(self, thread_id: str, run_id: str, *, payload: _T.SubmitToolOuputsToRunRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.SubmitToolOuputsToRun200, _HttpClientResponse], _Errors]: ...
    def submit_tool_ouputs_to_run(self, thread_id: str, run_id: str, *, payload: _T.SubmitToolOuputsToRunRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """When a run has the `status: "requires_action"` and `required_action.type` is `submit_tool_outputs`, this endpoint can be used to submit the outputs from the tool calls once they're all completed. All outputs must be submitted in a single request."""
        return self._json(_SUBMIT_TOOL_OUPUTS_TO_RUN, _c.encoded_path("/threads/{}/runs/{}/submit_tool_outputs", thread_id, run_id), None, _c.json_body(payload), include_response)

    def submit_tool_ouputs_to_run_sse(self, thread_id: str, run_id: str, *, payload: _T.SubmitToolOuputsToRunRequestJson) -> _Stream[_sse.DataEvent[_T.SubmitToolOuputsToRun200Sse], _SseErrors]:
        """When a run has the `status: "requires_action"` and `required_action.type` is `submit_tool_outputs`, this endpoint can be used to submit the outputs from the tool calls once they're all completed. All outputs must be submitted in a single request."""
        return self._sse(_SUBMIT_TOOL_OUPUTS_TO_RUN_SSE, _c.encoded_path("/threads/{}/runs/{}/submit_tool_outputs", thread_id, run_id), None, _c.json_body(payload), SubmitToolOuputsToRun200Sse)

    @_t.overload
    def create_upload(self, *, payload: _T.CreateUploadRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateUpload200, _Errors]: ...
    @_t.overload
    def create_upload(self, *, payload: _T.CreateUploadRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateUpload200, _HttpClientResponse], _Errors]: ...
    def create_upload(self, *, payload: _T.CreateUploadRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates an intermediate [Upload](https://developers.openai.com/api/reference/resources/uploads) object
        that you can add [Parts](https://developers.openai.com/api/reference/resources/uploads/subresources/parts) to.
        Currently, an Upload can accept at most 8 GB in total and expires after an
        hour after you create it.
        
        Once you complete the Upload, we will create a
        [File](https://developers.openai.com/api/reference/resources/files) object that contains all the parts
        you uploaded. This File is usable in the rest of our platform as a regular
        File object.
        
        For certain `purpose` values, the correct `mime_type` must be specified.
        Please refer to documentation for the
        [supported MIME types for your use case](https://developers.openai.com/api/docs/guides/tools-file-search#supported-files).
        
        For guidance on the proper filename extensions for each purpose, please
        follow the documentation on [creating a
        File](https://developers.openai.com/api/reference/resources/files/methods/create).
        
        Returns the Upload object with status `pending`."""
        return self._json(_CREATE_UPLOAD, "/uploads", None, _c.json_body(payload), include_response)

    @_t.overload
    def cancel_upload(self, upload_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.CancelUpload200, _Errors]: ...
    @_t.overload
    def cancel_upload(self, upload_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CancelUpload200, _HttpClientResponse], _Errors]: ...
    def cancel_upload(self, upload_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Cancels the Upload. No Parts may be added after an Upload is cancelled.
        
        Returns the Upload object with status `cancelled`."""
        return self._json(_CANCEL_UPLOAD, _c.encoded_path("/uploads/{}/cancel", upload_id), None, None, include_response)

    @_t.overload
    def complete_upload(self, upload_id: str, *, payload: _T.CompleteUploadRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CompleteUpload200, _Errors]: ...
    @_t.overload
    def complete_upload(self, upload_id: str, *, payload: _T.CompleteUploadRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CompleteUpload200, _HttpClientResponse], _Errors]: ...
    def complete_upload(self, upload_id: str, *, payload: _T.CompleteUploadRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Completes the [Upload](https://developers.openai.com/api/reference/resources/uploads).
        
        Within the returned Upload object, there is a nested [File](https://developers.openai.com/api/reference/resources/files) object that is ready to use in the rest of the platform.
        
        You can specify the order of the Parts by passing in an ordered list of the Part IDs.
        
        The number of bytes uploaded upon completion must match the number of bytes initially specified when creating the Upload object. No Parts may be added after an Upload is completed.
        Returns the Upload object with status `completed`, including an additional `file` property containing the created usable File object."""
        return self._json(_COMPLETE_UPLOAD, _c.encoded_path("/uploads/{}/complete", upload_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def add_upload_part(self, upload_id: str, *, payload: _T.AddUploadPartRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.AddUploadPart200, _Errors]: ...
    @_t.overload
    def add_upload_part(self, upload_id: str, *, payload: _T.AddUploadPartRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.AddUploadPart200, _HttpClientResponse], _Errors]: ...
    def add_upload_part(self, upload_id: str, *, payload: _T.AddUploadPartRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Adds a [Part](https://developers.openai.com/api/reference/resources/uploads/subresources/parts) to an [Upload](https://developers.openai.com/api/reference/resources/uploads) object. A Part represents a chunk of bytes from the file you are trying to upload.
        
        Each Part can be at most 64 MB, and you can add Parts until you hit the Upload maximum of 8 GB.
        
        It is possible to add multiple Parts in parallel. You can decide the intended order of the Parts when you [complete the Upload](https://developers.openai.com/api/reference/resources/uploads/methods/complete)."""
        return self._json(_ADD_UPLOAD_PART, _c.encoded_path("/uploads/{}/parts", upload_id), None, _c.form_body(payload), include_response)

    @_t.overload
    def list_vector_stores(self, *, params: _T.ListVectorStoresParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListVectorStores200, _Errors]: ...
    @_t.overload
    def list_vector_stores(self, *, params: _T.ListVectorStoresParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListVectorStores200, _HttpClientResponse], _Errors]: ...
    def list_vector_stores(self, *, params: _T.ListVectorStoresParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of vector stores."""
        return self._json(_LIST_VECTOR_STORES, "/vector_stores", params, None, include_response)

    @_t.overload
    def create_vector_store(self, *, payload: _T.CreateVectorStoreRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVectorStore200, _Errors]: ...
    @_t.overload
    def create_vector_store(self, *, payload: _T.CreateVectorStoreRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVectorStore200, _HttpClientResponse], _Errors]: ...
    def create_vector_store(self, *, payload: _T.CreateVectorStoreRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a vector store."""
        return self._json(_CREATE_VECTOR_STORE, "/vector_stores", None, _c.json_body(payload), include_response)

    @_t.overload
    def get_vector_store(self, vector_store_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetVectorStore200, _Errors]: ...
    @_t.overload
    def get_vector_store(self, vector_store_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetVectorStore200, _HttpClientResponse], _Errors]: ...
    def get_vector_store(self, vector_store_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a vector store."""
        return self._json(_GET_VECTOR_STORE, _c.encoded_path("/vector_stores/{}", vector_store_id), None, None, include_response)

    @_t.overload
    def modify_vector_store(self, vector_store_id: str, *, payload: _T.ModifyVectorStoreRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.ModifyVectorStore200, _Errors]: ...
    @_t.overload
    def modify_vector_store(self, vector_store_id: str, *, payload: _T.ModifyVectorStoreRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ModifyVectorStore200, _HttpClientResponse], _Errors]: ...
    def modify_vector_store(self, vector_store_id: str, *, payload: _T.ModifyVectorStoreRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Modifies a vector store."""
        return self._json(_MODIFY_VECTOR_STORE, _c.encoded_path("/vector_stores/{}", vector_store_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_vector_store(self, vector_store_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteVectorStore200, _Errors]: ...
    @_t.overload
    def delete_vector_store(self, vector_store_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteVectorStore200, _HttpClientResponse], _Errors]: ...
    def delete_vector_store(self, vector_store_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a vector store."""
        return self._json(_DELETE_VECTOR_STORE, _c.encoded_path("/vector_stores/{}", vector_store_id), None, None, include_response)

    @_t.overload
    def create_vector_store_file_batch(self, vector_store_id: str, *, payload: _T.CreateVectorStoreFileBatchRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVectorStoreFileBatch200, _Errors]: ...
    @_t.overload
    def create_vector_store_file_batch(self, vector_store_id: str, *, payload: _T.CreateVectorStoreFileBatchRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVectorStoreFileBatch200, _HttpClientResponse], _Errors]: ...
    def create_vector_store_file_batch(self, vector_store_id: str, *, payload: _T.CreateVectorStoreFileBatchRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a vector store file batch."""
        return self._json(_CREATE_VECTOR_STORE_FILE_BATCH, _c.encoded_path("/vector_stores/{}/file_batches", vector_store_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def get_vector_store_file_batch(self, vector_store_id: str, batch_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetVectorStoreFileBatch200, _Errors]: ...
    @_t.overload
    def get_vector_store_file_batch(self, vector_store_id: str, batch_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetVectorStoreFileBatch200, _HttpClientResponse], _Errors]: ...
    def get_vector_store_file_batch(self, vector_store_id: str, batch_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a vector store file batch."""
        return self._json(_GET_VECTOR_STORE_FILE_BATCH, _c.encoded_path("/vector_stores/{}/file_batches/{}", vector_store_id, batch_id), None, None, include_response)

    @_t.overload
    def cancel_vector_store_file_batch(self, vector_store_id: str, batch_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.CancelVectorStoreFileBatch200, _Errors]: ...
    @_t.overload
    def cancel_vector_store_file_batch(self, vector_store_id: str, batch_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CancelVectorStoreFileBatch200, _HttpClientResponse], _Errors]: ...
    def cancel_vector_store_file_batch(self, vector_store_id: str, batch_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Cancel a vector store file batch. This attempts to cancel the processing of files in this batch as soon as possible."""
        return self._json(_CANCEL_VECTOR_STORE_FILE_BATCH, _c.encoded_path("/vector_stores/{}/file_batches/{}/cancel", vector_store_id, batch_id), None, None, include_response)

    @_t.overload
    def list_files_in_vector_store_batch(self, vector_store_id: str, batch_id: str, *, params: _T.ListFilesInVectorStoreBatchParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListFilesInVectorStoreBatch200, _Errors]: ...
    @_t.overload
    def list_files_in_vector_store_batch(self, vector_store_id: str, batch_id: str, *, params: _T.ListFilesInVectorStoreBatchParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListFilesInVectorStoreBatch200, _HttpClientResponse], _Errors]: ...
    def list_files_in_vector_store_batch(self, vector_store_id: str, batch_id: str, *, params: _T.ListFilesInVectorStoreBatchParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of vector store files in a batch."""
        return self._json(_LIST_FILES_IN_VECTOR_STORE_BATCH, _c.encoded_path("/vector_stores/{}/file_batches/{}/files", vector_store_id, batch_id), params, None, include_response)

    @_t.overload
    def list_vector_store_files(self, vector_store_id: str, *, params: _T.ListVectorStoreFilesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListVectorStoreFiles200, _Errors]: ...
    @_t.overload
    def list_vector_store_files(self, vector_store_id: str, *, params: _T.ListVectorStoreFilesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListVectorStoreFiles200, _HttpClientResponse], _Errors]: ...
    def list_vector_store_files(self, vector_store_id: str, *, params: _T.ListVectorStoreFilesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of vector store files."""
        return self._json(_LIST_VECTOR_STORE_FILES, _c.encoded_path("/vector_stores/{}/files", vector_store_id), params, None, include_response)

    @_t.overload
    def create_vector_store_file(self, vector_store_id: str, *, payload: _T.CreateVectorStoreFileRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVectorStoreFile200, _Errors]: ...
    @_t.overload
    def create_vector_store_file(self, vector_store_id: str, *, payload: _T.CreateVectorStoreFileRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVectorStoreFile200, _HttpClientResponse], _Errors]: ...
    def create_vector_store_file(self, vector_store_id: str, *, payload: _T.CreateVectorStoreFileRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a vector store file by attaching a [File](https://developers.openai.com/api/reference/resources/files) to a [vector store](https://developers.openai.com/api/reference/resources/vector_stores)."""
        return self._json(_CREATE_VECTOR_STORE_FILE, _c.encoded_path("/vector_stores/{}/files", vector_store_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def get_vector_store_file(self, vector_store_id: str, file_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetVectorStoreFile200, _Errors]: ...
    @_t.overload
    def get_vector_store_file(self, vector_store_id: str, file_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetVectorStoreFile200, _HttpClientResponse], _Errors]: ...
    def get_vector_store_file(self, vector_store_id: str, file_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a vector store file."""
        return self._json(_GET_VECTOR_STORE_FILE, _c.encoded_path("/vector_stores/{}/files/{}", vector_store_id, file_id), None, None, include_response)

    @_t.overload
    def update_vector_store_file_attributes(self, vector_store_id: str, file_id: str, *, payload: _T.UpdateVectorStoreFileAttributesRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateVectorStoreFileAttributes200, _Errors]: ...
    @_t.overload
    def update_vector_store_file_attributes(self, vector_store_id: str, file_id: str, *, payload: _T.UpdateVectorStoreFileAttributesRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateVectorStoreFileAttributes200, _HttpClientResponse], _Errors]: ...
    def update_vector_store_file_attributes(self, vector_store_id: str, file_id: str, *, payload: _T.UpdateVectorStoreFileAttributesRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update attributes on a vector store file."""
        return self._json(_UPDATE_VECTOR_STORE_FILE_ATTRIBUTES, _c.encoded_path("/vector_stores/{}/files/{}", vector_store_id, file_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_vector_store_file(self, vector_store_id: str, file_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteVectorStoreFile200, _Errors]: ...
    @_t.overload
    def delete_vector_store_file(self, vector_store_id: str, file_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteVectorStoreFile200, _HttpClientResponse], _Errors]: ...
    def delete_vector_store_file(self, vector_store_id: str, file_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a vector store file. This will remove the file from the vector store but the file itself will not be deleted. To delete the file, use the [delete file](https://developers.openai.com/api/reference/resources/files/methods/delete) endpoint."""
        return self._json(_DELETE_VECTOR_STORE_FILE, _c.encoded_path("/vector_stores/{}/files/{}", vector_store_id, file_id), None, None, include_response)

    @_t.overload
    def retrieve_vector_store_file_content(self, vector_store_id: str, file_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveVectorStoreFileContent200, _Errors]: ...
    @_t.overload
    def retrieve_vector_store_file_content(self, vector_store_id: str, file_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveVectorStoreFileContent200, _HttpClientResponse], _Errors]: ...
    def retrieve_vector_store_file_content(self, vector_store_id: str, file_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieve the parsed contents of a vector store file."""
        return self._json(_RETRIEVE_VECTOR_STORE_FILE_CONTENT, _c.encoded_path("/vector_stores/{}/files/{}/content", vector_store_id, file_id), None, None, include_response)

    @_t.overload
    def search_vector_store(self, vector_store_id: str, *, payload: _T.SearchVectorStoreRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.SearchVectorStore200, _Errors]: ...
    @_t.overload
    def search_vector_store(self, vector_store_id: str, *, payload: _T.SearchVectorStoreRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.SearchVectorStore200, _HttpClientResponse], _Errors]: ...
    def search_vector_store(self, vector_store_id: str, *, payload: _T.SearchVectorStoreRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Search a vector store for relevant chunks based on a query and file attributes filter."""
        return self._json(_SEARCH_VECTOR_STORE, _c.encoded_path("/vector_stores/{}/search", vector_store_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def create_conversation(self, *, payload: _T.CreateConversationRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateConversation200, _Errors]: ...
    @_t.overload
    def create_conversation(self, *, payload: _T.CreateConversationRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateConversation200, _HttpClientResponse], _Errors]: ...
    def create_conversation(self, *, payload: _T.CreateConversationRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a conversation."""
        return self._json(_CREATE_CONVERSATION, "/conversations", None, _c.json_body(payload), include_response)

    @_t.overload
    def get_conversation(self, conversation_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetConversation200, _Errors]: ...
    @_t.overload
    def get_conversation(self, conversation_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetConversation200, _HttpClientResponse], _Errors]: ...
    def get_conversation(self, conversation_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a conversation"""
        return self._json(_GET_CONVERSATION, _c.encoded_path("/conversations/{}", conversation_id), None, None, include_response)

    @_t.overload
    def update_conversation(self, conversation_id: str, *, payload: _T.UpdateConversationRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateConversation200, _Errors]: ...
    @_t.overload
    def update_conversation(self, conversation_id: str, *, payload: _T.UpdateConversationRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateConversation200, _HttpClientResponse], _Errors]: ...
    def update_conversation(self, conversation_id: str, *, payload: _T.UpdateConversationRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update a conversation"""
        return self._json(_UPDATE_CONVERSATION, _c.encoded_path("/conversations/{}", conversation_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_conversation(self, conversation_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteConversation200, _Errors]: ...
    @_t.overload
    def delete_conversation(self, conversation_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteConversation200, _HttpClientResponse], _Errors]: ...
    def delete_conversation(self, conversation_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a conversation. Items in the conversation will not be deleted."""
        return self._json(_DELETE_CONVERSATION, _c.encoded_path("/conversations/{}", conversation_id), None, None, include_response)

    @_t.overload
    def getsafetycase(self, id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.Getsafetycase200, _Errors]: ...
    @_t.overload
    def getsafetycase(self, id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Getsafetycase200, _HttpClientResponse], _Errors]: ...
    def getsafetycase(self, id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a safety case by ID."""
        return self._json(_GETSAFETYCASE, _c.encoded_path("/safety/cases/{}", id), None, None, include_response)

    @_t.overload
    def getprojectsafetyalert(self, id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.Getprojectsafetyalert200, _Errors]: ...
    @_t.overload
    def getprojectsafetyalert(self, id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Getprojectsafetyalert200, _HttpClientResponse], _Errors]: ...
    def getprojectsafetyalert(self, id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a safety alert belonging to the authenticated API project."""
        return self._json(_GETPROJECTSAFETYALERT, _c.encoded_path("/safety/alerts/{}", id), None, None, include_response)

    @_t.overload
    def download_live_recording(self, session_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def download_live_recording(self, session_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def download_live_recording(self, session_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get Live session content"""
        return self._json(_DOWNLOAD_LIVE_RECORDING, _c.encoded_path("/live/sessions/{}/content", session_id), None, None, include_response)

    def download_live_recording_stream(self, session_id: str) -> _Stream[bytes, _HttpClientError]:
        """Get Live session content"""
        return self._binary(_DOWNLOAD_LIVE_RECORDING_STREAM, _c.encoded_path("/live/sessions/{}/content", session_id), None, None)

    @_t.overload
    def organization_decisionsusage(self, *, params: _T.OrganizationDecisionsusageParams, include_response: _t.Literal[False] = False) -> _Effect[_T.OrganizationDecisionsusage200, _Errors]: ...
    @_t.overload
    def organization_decisionsusage(self, *, params: _T.OrganizationDecisionsusageParams, include_response: _t.Literal[True]) -> _Effect[tuple[_T.OrganizationDecisionsusage200, _HttpClientResponse], _Errors]: ...
    def organization_decisionsusage(self, *, params: _T.OrganizationDecisionsusageParams, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get Decisions API usage details for the organization."""
        return self._json(_ORGANIZATION_DECISIONSUSAGE, "/organization/usage/decisions", params, None, include_response)

    @_t.overload
    def listexternalstorageconfigurations(self, *, params: _T.ListexternalstorageconfigurationsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.Listexternalstorageconfigurations200, _Errors]: ...
    @_t.overload
    def listexternalstorageconfigurations(self, *, params: _T.ListexternalstorageconfigurationsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Listexternalstorageconfigurations200, _HttpClientResponse], _Errors]: ...
    def listexternalstorageconfigurations(self, *, params: _T.ListexternalstorageconfigurationsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List the organization's customer-managed external storage configurations."""
        return self._json(_LISTEXTERNALSTORAGECONFIGURATIONS, "/organization/external_storage", params, None, include_response)

    @_t.overload
    def createanexternalstorageconfiguration(self, *, payload: _T.CreateanexternalstorageconfigurationRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.Createanexternalstorageconfiguration200, _Errors]: ...
    @_t.overload
    def createanexternalstorageconfiguration(self, *, payload: _T.CreateanexternalstorageconfigurationRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Createanexternalstorageconfiguration200, _HttpClientResponse], _Errors]: ...
    def createanexternalstorageconfiguration(self, *, payload: _T.CreateanexternalstorageconfigurationRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Register one customer-managed external storage configuration."""
        return self._json(_CREATEANEXTERNALSTORAGECONFIGURATION, "/organization/external_storage", None, _c.json_body(payload), include_response)

    @_t.overload
    def getanexternalstorageconfiguration(self, external_storage_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.Getanexternalstorageconfiguration200, _Errors]: ...
    @_t.overload
    def getanexternalstorageconfiguration(self, external_storage_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Getanexternalstorageconfiguration200, _HttpClientResponse], _Errors]: ...
    def getanexternalstorageconfiguration(self, external_storage_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get one customer-managed external storage configuration."""
        return self._json(_GETANEXTERNALSTORAGECONFIGURATION, _c.encoded_path("/organization/external_storage/{}", external_storage_id), None, None, include_response)

    @_t.overload
    def deleteanexternalstorageconfiguration(self, external_storage_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.Deleteanexternalstorageconfiguration200, _Errors]: ...
    @_t.overload
    def deleteanexternalstorageconfiguration(self, external_storage_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Deleteanexternalstorageconfiguration200, _HttpClientResponse], _Errors]: ...
    def deleteanexternalstorageconfiguration(self, external_storage_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Disconnect a customer-managed external storage configuration. Removing the project's last configuration restores organization-default retention if customer-managed retention was active. Repeating a deletion also completes any interrupted retention update. Cloud storage is unchanged."""
        return self._json(_DELETEANEXTERNALSTORAGECONFIGURATION, _c.encoded_path("/organization/external_storage/{}", external_storage_id), None, None, include_response)

    @_t.overload
    def validateanexternalstorageconfiguration(self, external_storage_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.Validateanexternalstorageconfiguration200, _Errors]: ...
    @_t.overload
    def validateanexternalstorageconfiguration(self, external_storage_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Validateanexternalstorageconfiguration200, _HttpClientResponse], _Errors]: ...
    def validateanexternalstorageconfiguration(self, external_storage_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Validate one customer-managed external storage configuration."""
        return self._json(_VALIDATEANEXTERNALSTORAGECONFIGURATION, _c.encoded_path("/organization/external_storage/{}/validate", external_storage_id), None, None, include_response)

    @_t.overload
    def getorganizationspendlimit(self, *, include_response: _t.Literal[False] = False) -> _Effect[_T.Getorganizationspendlimit200, _Errors]: ...
    @_t.overload
    def getorganizationspendlimit(self, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Getorganizationspendlimit200, _HttpClientResponse], _Errors]: ...
    def getorganizationspendlimit(self, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get the organization's hard spend limit."""
        return self._json(_GETORGANIZATIONSPENDLIMIT, "/organization/spend_limit", None, None, include_response)

    @_t.overload
    def updateorganizationspendlimit(self, *, payload: _T.UpdateorganizationspendlimitRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.Updateorganizationspendlimit200, _Errors]: ...
    @_t.overload
    def updateorganizationspendlimit(self, *, payload: _T.UpdateorganizationspendlimitRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Updateorganizationspendlimit200, _HttpClientResponse], _Errors]: ...
    def updateorganizationspendlimit(self, *, payload: _T.UpdateorganizationspendlimitRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create or replace the organization's hard spend limit."""
        return self._json(_UPDATEORGANIZATIONSPENDLIMIT, "/organization/spend_limit", None, _c.json_body(payload), include_response)

    @_t.overload
    def deleteorganizationspendlimit(self, *, include_response: _t.Literal[False] = False) -> _Effect[_T.Deleteorganizationspendlimit200, _Errors]: ...
    @_t.overload
    def deleteorganizationspendlimit(self, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Deleteorganizationspendlimit200, _HttpClientResponse], _Errors]: ...
    def deleteorganizationspendlimit(self, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete the organization's hard spend limit."""
        return self._json(_DELETEORGANIZATIONSPENDLIMIT, "/organization/spend_limit", None, None, include_response)

    @_t.overload
    def getprojectspendlimit(self, project_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.Getprojectspendlimit200, _Errors]: ...
    @_t.overload
    def getprojectspendlimit(self, project_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Getprojectspendlimit200, _HttpClientResponse], _Errors]: ...
    def getprojectspendlimit(self, project_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a project's hard spend limit."""
        return self._json(_GETPROJECTSPENDLIMIT, _c.encoded_path("/organization/projects/{}/spend_limit", project_id), None, None, include_response)

    @_t.overload
    def updateprojectspendlimit(self, project_id: str, *, payload: _T.UpdateprojectspendlimitRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.Updateprojectspendlimit200, _Errors]: ...
    @_t.overload
    def updateprojectspendlimit(self, project_id: str, *, payload: _T.UpdateprojectspendlimitRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Updateprojectspendlimit200, _HttpClientResponse], _Errors]: ...
    def updateprojectspendlimit(self, project_id: str, *, payload: _T.UpdateprojectspendlimitRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create or replace a project's hard spend limit."""
        return self._json(_UPDATEPROJECTSPENDLIMIT, _c.encoded_path("/organization/projects/{}/spend_limit", project_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def deleteprojectspendlimit(self, project_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.Deleteprojectspendlimit200, _Errors]: ...
    @_t.overload
    def deleteprojectspendlimit(self, project_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Deleteprojectspendlimit200, _HttpClientResponse], _Errors]: ...
    def deleteprojectspendlimit(self, project_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a project's hard spend limit."""
        return self._json(_DELETEPROJECTSPENDLIMIT, _c.encoded_path("/organization/projects/{}/spend_limit", project_id), None, None, include_response)

    @_t.overload
    def createan_ap_ikeyforaserviceaccount(self, project_id: str, service_account_id: str, *, payload: _T.CreateanAPIkeyforaserviceaccountRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateanAPIkeyforaserviceaccount200, _Errors]: ...
    @_t.overload
    def createan_ap_ikeyforaserviceaccount(self, project_id: str, service_account_id: str, *, payload: _T.CreateanAPIkeyforaserviceaccountRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateanAPIkeyforaserviceaccount200, _HttpClientResponse], _Errors]: ...
    def createan_ap_ikeyforaserviceaccount(self, project_id: str, service_account_id: str, *, payload: _T.CreateanAPIkeyforaserviceaccountRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates an API key for a service account in the project."""
        return self._json(_CREATEAN_AP_IKEYFORASERVICEACCOUNT, _c.encoded_path("/organization/projects/{}/service_accounts/{}/api_keys", project_id, service_account_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def createcontentprovenancecheck(self, *, payload: _T.CreatecontentprovenancecheckRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.Createcontentprovenancecheck200, _Errors]: ...
    @_t.overload
    def createcontentprovenancecheck(self, *, payload: _T.CreatecontentprovenancecheckRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Createcontentprovenancecheck200, _HttpClientResponse], _Errors]: ...
    def createcontentprovenancecheck(self, *, payload: _T.CreatecontentprovenancecheckRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Check whether an image or audio file contains known OpenAI provenance signals. [Learn more about content provenance](https://developers.openai.com/api/docs/guides/content-provenance).
        
        If `not_detected`, it means the tool did not find supported signals in the uploaded file. The content could still have been generated by OpenAI if the metadata was stripped or has evidence of tampering, the watermark was degraded, it comes from a legacy generation model, or it was created before provenance signals were available. Content could also still be AI-generated by another company's model, which the tool currently does not detect."""
        return self._json(_CREATECONTENTPROVENANCECHECK, "/content_provenance_checks", None, _c.form_body(payload), include_response)

    @_t.overload
    def list_videos(self, *, params: _T.ListVideosParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListVideos200, _Errors]: ...
    @_t.overload
    def list_videos(self, *, params: _T.ListVideosParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListVideos200, _HttpClientResponse], _Errors]: ...
    def list_videos(self, *, params: _T.ListVideosParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List recently generated videos for the current project."""
        return self._json(_LIST_VIDEOS, "/videos", params, None, include_response)

    @_t.overload
    def create_video(self, *, payload: _T.CreateVideoRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVideo200, _Errors]: ...
    @_t.overload
    def create_video(self, *, payload: _T.CreateVideoRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVideo200, _HttpClientResponse], _Errors]: ...
    def create_video(self, *, payload: _T.CreateVideoRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new video generation job from a prompt and optional reference assets."""
        return self._json(_CREATE_VIDEO, "/videos", None, _c.form_body(payload), include_response)

    @_t.overload
    def create_video_character(self, *, payload: _T.CreateVideoCharacterRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVideoCharacter200, _Errors]: ...
    @_t.overload
    def create_video_character(self, *, payload: _T.CreateVideoCharacterRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVideoCharacter200, _HttpClientResponse], _Errors]: ...
    def create_video_character(self, *, payload: _T.CreateVideoCharacterRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a character from an uploaded video."""
        return self._json(_CREATE_VIDEO_CHARACTER, "/videos/characters", None, _c.form_body(payload), include_response)

    @_t.overload
    def get_video_character(self, character_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetVideoCharacter200, _Errors]: ...
    @_t.overload
    def get_video_character(self, character_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetVideoCharacter200, _HttpClientResponse], _Errors]: ...
    def get_video_character(self, character_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Fetch a character."""
        return self._json(_GET_VIDEO_CHARACTER, _c.encoded_path("/videos/characters/{}", character_id), None, None, include_response)

    @_t.overload
    def create_video_edit(self, *, payload: _T.CreateVideoEditRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVideoEdit200, _Errors]: ...
    @_t.overload
    def create_video_edit(self, *, payload: _T.CreateVideoEditRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVideoEdit200, _HttpClientResponse], _Errors]: ...
    def create_video_edit(self, *, payload: _T.CreateVideoEditRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new video generation job by editing a source video or existing generated video."""
        return self._json(_CREATE_VIDEO_EDIT, "/videos/edits", None, _c.form_body(payload), include_response)

    @_t.overload
    def create_video_extend(self, *, payload: _T.CreateVideoExtendRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVideoExtend200, _Errors]: ...
    @_t.overload
    def create_video_extend(self, *, payload: _T.CreateVideoExtendRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVideoExtend200, _HttpClientResponse], _Errors]: ...
    def create_video_extend(self, *, payload: _T.CreateVideoExtendRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create an extension of a completed video."""
        return self._json(_CREATE_VIDEO_EXTEND, "/videos/extensions", None, _c.form_body(payload), include_response)

    @_t.overload
    def get_video(self, video_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetVideo200, _Errors]: ...
    @_t.overload
    def get_video(self, video_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetVideo200, _HttpClientResponse], _Errors]: ...
    def get_video(self, video_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Fetch the latest metadata for a generated video."""
        return self._json(_GET_VIDEO, _c.encoded_path("/videos/{}", video_id), None, None, include_response)

    @_t.overload
    def delete_video(self, video_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteVideo200, _Errors]: ...
    @_t.overload
    def delete_video(self, video_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteVideo200, _HttpClientResponse], _Errors]: ...
    def delete_video(self, video_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Permanently delete a completed or failed video and its stored assets."""
        return self._json(_DELETE_VIDEO, _c.encoded_path("/videos/{}", video_id), None, None, include_response)

    @_t.overload
    def retrieve_video_content(self, video_id: str, *, params: _T.RetrieveVideoContentParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def retrieve_video_content(self, video_id: str, *, params: _T.RetrieveVideoContentParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def retrieve_video_content(self, video_id: str, *, params: _T.RetrieveVideoContentParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Download the generated video bytes or a derived preview asset.
        
        Streams the rendered video content for the specified video job."""
        return self._json(_RETRIEVE_VIDEO_CONTENT, _c.encoded_path("/videos/{}/content", video_id), params, None, include_response)

    def retrieve_video_content_stream(self, video_id: str, *, params: _T.RetrieveVideoContentParams | None = None) -> _Stream[bytes, _HttpClientError]:
        """Download the generated video bytes or a derived preview asset.
        
        Streams the rendered video content for the specified video job."""
        return self._binary(_RETRIEVE_VIDEO_CONTENT_STREAM, _c.encoded_path("/videos/{}/content", video_id), params, None)

    @_t.overload
    def create_video_remix(self, video_id: str, *, payload: _T.CreateVideoRemixRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVideoRemix200, _Errors]: ...
    @_t.overload
    def create_video_remix(self, video_id: str, *, payload: _T.CreateVideoRemixRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVideoRemix200, _HttpClientResponse], _Errors]: ...
    def create_video_remix(self, video_id: str, *, payload: _T.CreateVideoRemixRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a remix of a completed video using a refreshed prompt."""
        return self._json(_CREATE_VIDEO_REMIX, _c.encoded_path("/videos/{}/remix", video_id), None, _c.form_body(payload), include_response)

    @_t.overload
    def getinputtokencounts(self, *, payload: _T.GetinputtokencountsRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.Getinputtokencounts200, _Errors]: ...
    @_t.overload
    def getinputtokencounts(self, *, payload: _T.GetinputtokencountsRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Getinputtokencounts200, _HttpClientResponse], _Errors]: ...
    def getinputtokencounts(self, *, payload: _T.GetinputtokencountsRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns input token counts of the request.
        
        Returns an object with `object` set to `response.input_tokens` and an `input_tokens` count."""
        return self._json(_GETINPUTTOKENCOUNTS, "/responses/input_tokens", None, _c.json_body(payload), include_response)

    @_t.overload
    def compactconversation(self, *, payload: _T.CompactconversationRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.Compactconversation200, _Errors]: ...
    @_t.overload
    def compactconversation(self, *, payload: _T.CompactconversationRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.Compactconversation200, _HttpClientResponse], _Errors]: ...
    def compactconversation(self, *, payload: _T.CompactconversationRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Compact a conversation. Returns a compacted response object.
        
        Learn when and how to compact long-running conversations in the [conversation state guide](https://developers.openai.com/api/docs/guides/conversation-state#managing-the-context-window). For ZDR-compatible compaction details, see [Compaction (advanced)](https://developers.openai.com/api/docs/guides/conversation-state#compaction-advanced)."""
        return self._json(_COMPACTCONVERSATION, "/responses/compact", None, _c.json_body(payload), include_response)

    @_t.overload
    def list_skills(self, *, params: _T.ListSkillsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListSkills200, _Errors]: ...
    @_t.overload
    def list_skills(self, *, params: _T.ListSkillsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListSkills200, _HttpClientResponse], _Errors]: ...
    def list_skills(self, *, params: _T.ListSkillsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List all skills for the current project."""
        return self._json(_LIST_SKILLS, "/skills", params, None, include_response)

    @_t.overload
    def create_skill(self, *, payload: _T.CreateSkillRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateSkill200, _Errors]: ...
    @_t.overload
    def create_skill(self, *, payload: _T.CreateSkillRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateSkill200, _HttpClientResponse], _Errors]: ...
    def create_skill(self, *, payload: _T.CreateSkillRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new skill."""
        return self._json(_CREATE_SKILL, "/skills", None, _c.form_body(payload), include_response)

    @_t.overload
    def get_skill(self, skill_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetSkill200, _Errors]: ...
    @_t.overload
    def get_skill(self, skill_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetSkill200, _HttpClientResponse], _Errors]: ...
    def get_skill(self, skill_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a skill by its ID."""
        return self._json(_GET_SKILL, _c.encoded_path("/skills/{}", skill_id), None, None, include_response)

    @_t.overload
    def update_skill_default_version(self, skill_id: str, *, payload: _T.UpdateSkillDefaultVersionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateSkillDefaultVersion200, _Errors]: ...
    @_t.overload
    def update_skill_default_version(self, skill_id: str, *, payload: _T.UpdateSkillDefaultVersionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateSkillDefaultVersion200, _HttpClientResponse], _Errors]: ...
    def update_skill_default_version(self, skill_id: str, *, payload: _T.UpdateSkillDefaultVersionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Update the default version pointer for a skill."""
        return self._json(_UPDATE_SKILL_DEFAULT_VERSION, _c.encoded_path("/skills/{}", skill_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_skill(self, skill_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteSkill200, _Errors]: ...
    @_t.overload
    def delete_skill(self, skill_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteSkill200, _HttpClientResponse], _Errors]: ...
    def delete_skill(self, skill_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a skill by its ID."""
        return self._json(_DELETE_SKILL, _c.encoded_path("/skills/{}", skill_id), None, None, include_response)

    @_t.overload
    def get_skill_content(self, skill_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def get_skill_content(self, skill_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def get_skill_content(self, skill_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Download a skill zip bundle by its ID."""
        return self._json(_GET_SKILL_CONTENT, _c.encoded_path("/skills/{}/content", skill_id), None, None, include_response)

    def get_skill_content_stream(self, skill_id: str) -> _Stream[bytes, _HttpClientError]:
        """Download a skill zip bundle by its ID."""
        return self._binary(_GET_SKILL_CONTENT_STREAM, _c.encoded_path("/skills/{}/content", skill_id), None, None)

    @_t.overload
    def list_skill_versions(self, skill_id: str, *, params: _T.ListSkillVersionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListSkillVersions200, _Errors]: ...
    @_t.overload
    def list_skill_versions(self, skill_id: str, *, params: _T.ListSkillVersionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListSkillVersions200, _HttpClientResponse], _Errors]: ...
    def list_skill_versions(self, skill_id: str, *, params: _T.ListSkillVersionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List skill versions for a skill."""
        return self._json(_LIST_SKILL_VERSIONS, _c.encoded_path("/skills/{}/versions", skill_id), params, None, include_response)

    @_t.overload
    def create_skill_version(self, skill_id: str, *, payload: _T.CreateSkillVersionRequestFormData, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateSkillVersion200, _Errors]: ...
    @_t.overload
    def create_skill_version(self, skill_id: str, *, payload: _T.CreateSkillVersionRequestFormData, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateSkillVersion200, _HttpClientResponse], _Errors]: ...
    def create_skill_version(self, skill_id: str, *, payload: _T.CreateSkillVersionRequestFormData, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a new immutable skill version."""
        return self._json(_CREATE_SKILL_VERSION, _c.encoded_path("/skills/{}/versions", skill_id), None, _c.form_body(payload), include_response)

    @_t.overload
    def get_skill_version(self, skill_id: str, version: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetSkillVersion200, _Errors]: ...
    @_t.overload
    def get_skill_version(self, skill_id: str, version: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetSkillVersion200, _HttpClientResponse], _Errors]: ...
    def get_skill_version(self, skill_id: str, version: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Get a specific skill version."""
        return self._json(_GET_SKILL_VERSION, _c.encoded_path("/skills/{}/versions/{}", skill_id, version), None, None, include_response)

    @_t.overload
    def delete_skill_version(self, skill_id: str, version: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteSkillVersion200, _Errors]: ...
    @_t.overload
    def delete_skill_version(self, skill_id: str, version: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteSkillVersion200, _HttpClientResponse], _Errors]: ...
    def delete_skill_version(self, skill_id: str, version: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a skill version."""
        return self._json(_DELETE_SKILL_VERSION, _c.encoded_path("/skills/{}/versions/{}", skill_id, version), None, None, include_response)

    @_t.overload
    def get_skill_version_content(self, skill_id: str, version: str, *, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def get_skill_version_content(self, skill_id: str, version: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def get_skill_version_content(self, skill_id: str, version: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Download a skill version zip bundle."""
        return self._json(_GET_SKILL_VERSION_CONTENT, _c.encoded_path("/skills/{}/versions/{}/content", skill_id, version), None, None, include_response)

    def get_skill_version_content_stream(self, skill_id: str, version: str) -> _Stream[bytes, _HttpClientError]:
        """Download a skill version zip bundle."""
        return self._binary(_GET_SKILL_VERSION_CONTENT_STREAM, _c.encoded_path("/skills/{}/versions/{}/content", skill_id, version), None, None)

    @_t.overload
    def cancel_chat_session_method(self, session_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.CancelChatSessionMethod200, _Errors]: ...
    @_t.overload
    def cancel_chat_session_method(self, session_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CancelChatSessionMethod200, _HttpClientResponse], _Errors]: ...
    def cancel_chat_session_method(self, session_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Cancel an active ChatKit session and return its most recent metadata.
        
        Cancelling prevents new requests from using the issued client secret."""
        return self._json(_CANCEL_CHAT_SESSION_METHOD, _c.encoded_path("/chatkit/sessions/{}/cancel", session_id), None, None, include_response)

    @_t.overload
    def create_chat_session_method(self, *, payload: _T.CreateChatSessionMethodRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateChatSessionMethod200, _Errors]: ...
    @_t.overload
    def create_chat_session_method(self, *, payload: _T.CreateChatSessionMethodRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateChatSessionMethod200, _HttpClientResponse], _Errors]: ...
    def create_chat_session_method(self, *, payload: _T.CreateChatSessionMethodRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Create a ChatKit session."""
        return self._json(_CREATE_CHAT_SESSION_METHOD, "/chatkit/sessions", None, _c.json_body(payload), include_response)

    @_t.overload
    def list_thread_items_method(self, thread_id: str, *, params: _T.ListThreadItemsMethodParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListThreadItemsMethod200, _Errors]: ...
    @_t.overload
    def list_thread_items_method(self, thread_id: str, *, params: _T.ListThreadItemsMethodParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListThreadItemsMethod200, _HttpClientResponse], _Errors]: ...
    def list_thread_items_method(self, thread_id: str, *, params: _T.ListThreadItemsMethodParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List items that belong to a ChatKit thread."""
        return self._json(_LIST_THREAD_ITEMS_METHOD, _c.encoded_path("/chatkit/threads/{}/items", thread_id), params, None, include_response)

    @_t.overload
    def get_thread_method(self, thread_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.GetThreadMethod200, _Errors]: ...
    @_t.overload
    def get_thread_method(self, thread_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.GetThreadMethod200, _HttpClientResponse], _Errors]: ...
    def get_thread_method(self, thread_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieve a ChatKit thread by its identifier."""
        return self._json(_GET_THREAD_METHOD, _c.encoded_path("/chatkit/threads/{}", thread_id), None, None, include_response)

    @_t.overload
    def delete_thread_method(self, thread_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteThreadMethod200, _Errors]: ...
    @_t.overload
    def delete_thread_method(self, thread_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteThreadMethod200, _HttpClientResponse], _Errors]: ...
    def delete_thread_method(self, thread_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Delete a ChatKit thread along with its items and stored attachments."""
        return self._json(_DELETE_THREAD_METHOD, _c.encoded_path("/chatkit/threads/{}", thread_id), None, None, include_response)

    @_t.overload
    def list_threads_method(self, *, params: _T.ListThreadsMethodParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListThreadsMethod200, _Errors]: ...
    @_t.overload
    def list_threads_method(self, *, params: _T.ListThreadsMethodParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListThreadsMethod200, _HttpClientResponse], _Errors]: ...
    def list_threads_method(self, *, params: _T.ListThreadsMethodParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """List ChatKit threads with optional pagination and user filters."""
        return self._json(_LIST_THREADS_METHOD, "/chatkit/threads", params, None, include_response)

    @_t.overload
    def create_decision(self, *, payload: _T.CreateDecisionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateDecision200, _PlainErrors]: ...
    @_t.overload
    def create_decision(self, *, payload: _T.CreateDecisionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateDecision200, _HttpClientResponse], _PlainErrors]: ...
    def create_decision(self, *, payload: _T.CreateDecisionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _PlainErrors]:
        """Use this endpoint to ask classification or scoring questions about the same input. You’ll get the answers back in the order you asked the questions.
        
        For text, you can pass a string. You can also send user messages containing `input_text` and `input_image` parts, with up to 128 images per request. Images can be base64 data URLs or publicly accessible HTTP(S) URLs. File IDs aren’t accepted. Other message roles, function calls, files, audio, and item references aren’t supported.
        
        Sometimes a question returns a refusal instead of an answer. The result has type `refusal` and includes the question’s name, or `null` if you didn’t give it one."""
        return self._json(_CREATE_DECISION, "/decisions", None, _c.json_body(payload), include_response)

    @_t.overload
    def list_agent_environments(self, *, params: _T.ListAgentEnvironmentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentEnvironments200, _Errors]: ...
    @_t.overload
    def list_agent_environments(self, *, params: _T.ListAgentEnvironmentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentEnvironments200, _HttpClientResponse], _Errors]: ...
    def list_agent_environments(self, *, params: _T.ListAgentEnvironmentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists OpenAI-hosted environments owned by the authenticated principal. Requires access to the prewarming beta."""
        return self._json(_LIST_AGENT_ENVIRONMENTS, "/agents/environments", params, None, include_response)

    @_t.overload
    def create_agent_environment(self, *, payload: _T.CreateAgentEnvironmentRequestJson, params: _T.CreateAgentEnvironmentParams2 | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateAgentEnvironment201, _Errors]: ...
    @_t.overload
    def create_agent_environment(self, *, payload: _T.CreateAgentEnvironmentRequestJson, params: _T.CreateAgentEnvironmentParams2 | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateAgentEnvironment201, _HttpClientResponse], _Errors]: ...
    def create_agent_environment(self, *, payload: _T.CreateAgentEnvironmentRequestJson, params: _T.CreateAgentEnvironmentParams2 | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates an OpenAI-hosted environment before creating a session. Requires access to the prewarming beta."""
        return self._json(_CREATE_AGENT_ENVIRONMENT, "/agents/environments", params, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_agent_environment(self, environment_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveAgentEnvironment200, _Errors]: ...
    @_t.overload
    def retrieve_agent_environment(self, environment_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveAgentEnvironment200, _HttpClientResponse], _Errors]: ...
    def retrieve_agent_environment(self, environment_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves an execution environment's connection status and safe installed metadata. See [environment lifecycle](https://developers.openai.com/api/docs/guides/agents-api/environments/lifecycle)."""
        return self._json(_RETRIEVE_AGENT_ENVIRONMENT, _c.encoded_path("/agents/environments/{}", environment_id), None, None, include_response)

    @_t.overload
    def list_agent_environment_files(self, environment_id: str, *, params: _T.ListAgentEnvironmentFilesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentEnvironmentFiles200, _Errors]: ...
    @_t.overload
    def list_agent_environment_files(self, environment_id: str, *, params: _T.ListAgentEnvironmentFilesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentEnvironmentFiles200, _HttpClientResponse], _Errors]: ...
    def list_agent_environment_files(self, environment_id: str, *, params: _T.ListAgentEnvironmentFilesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists live files on a connected execution environment with optional directory filtering and opaque cursor pagination. See [environment files](https://developers.openai.com/api/docs/guides/agents-api/environments/files)."""
        return self._json(_LIST_AGENT_ENVIRONMENT_FILES, _c.encoded_path("/agents/environments/{}/files", environment_id), params, None, include_response)

    @_t.overload
    def create_agent_environment_file(self, environment_id: str, *, payload: _T.CreateAgentEnvironmentFileRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateAgentEnvironmentFile201, _Errors]: ...
    @_t.overload
    def create_agent_environment_file(self, environment_id: str, *, payload: _T.CreateAgentEnvironmentFileRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateAgentEnvironmentFile201, _HttpClientResponse], _Errors]: ...
    def create_agent_environment_file(self, environment_id: str, *, payload: _T.CreateAgentEnvironmentFileRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Copies inline bytes or a Files API file into a connected execution environment. See [environment files](https://developers.openai.com/api/docs/guides/agents-api/environments/files)."""
        return self._json(_CREATE_AGENT_ENVIRONMENT_FILE, _c.encoded_path("/agents/environments/{}/files", environment_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def list_agent_session_subagents(self, session_id: str, *, params: _T.ListAgentSessionSubagentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentSessionSubagents200, _Errors]: ...
    @_t.overload
    def list_agent_session_subagents(self, session_id: str, *, params: _T.ListAgentSessionSubagentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentSessionSubagents200, _HttpClientResponse], _Errors]: ...
    def list_agent_session_subagents(self, session_id: str, *, params: _T.ListAgentSessionSubagentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists subagents in a session, including nested and closed subagents. See [subagent workflows](https://developers.openai.com/api/docs/guides/agents-api/multi-agent)."""
        return self._json(_LIST_AGENT_SESSION_SUBAGENTS, _c.encoded_path("/agents/sessions/{}/subagents", session_id), params, None, include_response)

    @_t.overload
    def retrieve_agent_session_subagent(self, session_id: str, subagent_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveAgentSessionSubagent200, _Errors]: ...
    @_t.overload
    def retrieve_agent_session_subagent(self, session_id: str, subagent_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveAgentSessionSubagent200, _HttpClientResponse], _Errors]: ...
    def retrieve_agent_session_subagent(self, session_id: str, subagent_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a subagent belonging to this session. See [subagent workflows](https://developers.openai.com/api/docs/guides/agents-api/multi-agent)."""
        return self._json(_RETRIEVE_AGENT_SESSION_SUBAGENT, _c.encoded_path("/agents/sessions/{}/subagents/{}", session_id, subagent_id), None, None, include_response)

    @_t.overload
    def list_agent_session_subagent_items(self, session_id: str, subagent_id: str, *, params: _T.ListAgentSessionSubagentItemsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentSessionSubagentItems200, _Errors]: ...
    @_t.overload
    def list_agent_session_subagent_items(self, session_id: str, subagent_id: str, *, params: _T.ListAgentSessionSubagentItemsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentSessionSubagentItems200, _HttpClientResponse], _Errors]: ...
    def list_agent_session_subagent_items(self, session_id: str, subagent_id: str, *, params: _T.ListAgentSessionSubagentItemsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists this subagent's own items across all of its turns. See [subagent workflows](https://developers.openai.com/api/docs/guides/agents-api/multi-agent)."""
        return self._json(_LIST_AGENT_SESSION_SUBAGENT_ITEMS, _c.encoded_path("/agents/sessions/{}/subagents/{}/items", session_id, subagent_id), params, None, include_response)

    @_t.overload
    def list_agent_session_subagent_turns(self, session_id: str, subagent_id: str, *, params: _T.ListAgentSessionSubagentTurnsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentSessionSubagentTurns200, _Errors]: ...
    @_t.overload
    def list_agent_session_subagent_turns(self, session_id: str, subagent_id: str, *, params: _T.ListAgentSessionSubagentTurnsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentSessionSubagentTurns200, _HttpClientResponse], _Errors]: ...
    def list_agent_session_subagent_turns(self, session_id: str, subagent_id: str, *, params: _T.ListAgentSessionSubagentTurnsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists all turns of this subagent, including turns after a resume. See [subagent workflows](https://developers.openai.com/api/docs/guides/agents-api/multi-agent)."""
        return self._json(_LIST_AGENT_SESSION_SUBAGENT_TURNS, _c.encoded_path("/agents/sessions/{}/subagents/{}/turns", session_id, subagent_id), params, None, include_response)

    @_t.overload
    def retrieve_agent_session_subagent_turn(self, session_id: str, subagent_id: str, turn_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveAgentSessionSubagentTurn200, _Errors]: ...
    @_t.overload
    def retrieve_agent_session_subagent_turn(self, session_id: str, subagent_id: str, turn_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveAgentSessionSubagentTurn200, _HttpClientResponse], _Errors]: ...
    def retrieve_agent_session_subagent_turn(self, session_id: str, subagent_id: str, turn_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a turn belonging to this subagent. See [subagent workflows](https://developers.openai.com/api/docs/guides/agents-api/multi-agent)."""
        return self._json(_RETRIEVE_AGENT_SESSION_SUBAGENT_TURN, _c.encoded_path("/agents/sessions/{}/subagents/{}/turns/{}", session_id, subagent_id, turn_id), None, None, include_response)

    @_t.overload
    def list_agent_session_subagent_turn_items(self, session_id: str, subagent_id: str, turn_id: str, *, params: _T.ListAgentSessionSubagentTurnItemsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentSessionSubagentTurnItems200, _Errors]: ...
    @_t.overload
    def list_agent_session_subagent_turn_items(self, session_id: str, subagent_id: str, turn_id: str, *, params: _T.ListAgentSessionSubagentTurnItemsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentSessionSubagentTurnItems200, _HttpClientResponse], _Errors]: ...
    def list_agent_session_subagent_turn_items(self, session_id: str, subagent_id: str, turn_id: str, *, params: _T.ListAgentSessionSubagentTurnItemsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists items belonging to one turn of this subagent. See [subagent workflows](https://developers.openai.com/api/docs/guides/agents-api/multi-agent)."""
        return self._json(_LIST_AGENT_SESSION_SUBAGENT_TURN_ITEMS, _c.encoded_path("/agents/sessions/{}/subagents/{}/turns/{}/items", session_id, subagent_id, turn_id), params, None, include_response)

    @_t.overload
    def list_agents(self, *, params: _T.ListAgentsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgents200, _Errors]: ...
    @_t.overload
    def list_agents(self, *, params: _T.ListAgentsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgents200, _HttpClientResponse], _Errors]: ...
    def list_agents(self, *, params: _T.ListAgentsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists reusable agents in the current project. See [agent configuration](https://developers.openai.com/api/docs/guides/agents-api/configuration)."""
        return self._json(_LIST_AGENTS, "/agents", params, None, include_response)

    @_t.overload
    def create_agent(self, *, payload: _T.CreateAgentRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateAgent201, _Errors]: ...
    @_t.overload
    def create_agent(self, *, payload: _T.CreateAgentRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateAgent201, _HttpClientResponse], _Errors]: ...
    def create_agent(self, *, payload: _T.CreateAgentRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a reusable agent without storing credentials. See [agent configuration](https://developers.openai.com/api/docs/guides/agents-api/configuration)."""
        return self._json(_CREATE_AGENT, "/agents", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_agent(self, agent_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveAgent200, _Errors]: ...
    @_t.overload
    def retrieve_agent(self, agent_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveAgent200, _HttpClientResponse], _Errors]: ...
    def retrieve_agent(self, agent_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a reusable agent by ID. See [agent configuration](https://developers.openai.com/api/docs/guides/agents-api/configuration)."""
        return self._json(_RETRIEVE_AGENT, _c.encoded_path("/agents/{}", agent_id), None, None, include_response)

    @_t.overload
    def update_agent(self, agent_id: str, *, payload: _T.UpdateAgentRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateAgent200, _Errors]: ...
    @_t.overload
    def update_agent(self, agent_id: str, *, payload: _T.UpdateAgentRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateAgent200, _HttpClientResponse], _Errors]: ...
    def update_agent(self, agent_id: str, *, payload: _T.UpdateAgentRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates a reusable agent. See [agent configuration](https://developers.openai.com/api/docs/guides/agents-api/configuration)."""
        return self._json(_UPDATE_AGENT, _c.encoded_path("/agents/{}", agent_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_agent(self, agent_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteAgent200, _Errors]: ...
    @_t.overload
    def delete_agent(self, agent_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteAgent200, _HttpClientResponse], _Errors]: ...
    def delete_agent(self, agent_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a reusable agent. See [agent configuration](https://developers.openai.com/api/docs/guides/agents-api/configuration)."""
        return self._json(_DELETE_AGENT, _c.encoded_path("/agents/{}", agent_id), None, None, include_response)

    @_t.overload
    def list_agent_environment_templates(self, *, params: _T.ListAgentEnvironmentTemplatesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentEnvironmentTemplates200, _Errors]: ...
    @_t.overload
    def list_agent_environment_templates(self, *, params: _T.ListAgentEnvironmentTemplatesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentEnvironmentTemplates200, _HttpClientResponse], _Errors]: ...
    def list_agent_environment_templates(self, *, params: _T.ListAgentEnvironmentTemplatesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists reusable environment templates without returning confidential values. See [reusing a hosted setup](https://developers.openai.com/api/docs/guides/agents-api/tools#reuse-a-hosted-plugin-setup)."""
        return self._json(_LIST_AGENT_ENVIRONMENT_TEMPLATES, "/agents/environments/templates", params, None, include_response)

    @_t.overload
    def create_agent_environment_template(self, *, payload: _T.CreateAgentEnvironmentTemplateRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateAgentEnvironmentTemplate201, _Errors]: ...
    @_t.overload
    def create_agent_environment_template(self, *, payload: _T.CreateAgentEnvironmentTemplateRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateAgentEnvironmentTemplate201, _HttpClientResponse], _Errors]: ...
    def create_agent_environment_template(self, *, payload: _T.CreateAgentEnvironmentTemplateRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates reusable environment configuration without returning confidential setup commands or environment values. See [reusing a hosted setup](https://developers.openai.com/api/docs/guides/agents-api/tools#reuse-a-hosted-plugin-setup)."""
        return self._json(_CREATE_AGENT_ENVIRONMENT_TEMPLATE, "/agents/environments/templates", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_agent_environment_template(self, environment_template_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveAgentEnvironmentTemplate200, _Errors]: ...
    @_t.overload
    def retrieve_agent_environment_template(self, environment_template_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveAgentEnvironmentTemplate200, _HttpClientResponse], _Errors]: ...
    def retrieve_agent_environment_template(self, environment_template_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves reusable environment configuration without returning confidential values. See [reusing a hosted setup](https://developers.openai.com/api/docs/guides/agents-api/tools#reuse-a-hosted-plugin-setup)."""
        return self._json(_RETRIEVE_AGENT_ENVIRONMENT_TEMPLATE, _c.encoded_path("/agents/environments/templates/{}", environment_template_id), None, None, include_response)

    @_t.overload
    def update_agent_environment_template(self, environment_template_id: str, *, payload: _T.UpdateAgentEnvironmentTemplateRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateAgentEnvironmentTemplate200, _Errors]: ...
    @_t.overload
    def update_agent_environment_template(self, environment_template_id: str, *, payload: _T.UpdateAgentEnvironmentTemplateRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateAgentEnvironmentTemplate200, _HttpClientResponse], _Errors]: ...
    def update_agent_environment_template(self, environment_template_id: str, *, payload: _T.UpdateAgentEnvironmentTemplateRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates reusable environment configuration without returning confidential values. See [reusing a hosted setup](https://developers.openai.com/api/docs/guides/agents-api/tools#reuse-a-hosted-plugin-setup)."""
        return self._json(_UPDATE_AGENT_ENVIRONMENT_TEMPLATE, _c.encoded_path("/agents/environments/templates/{}", environment_template_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_agent_environment_template(self, environment_template_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteAgentEnvironmentTemplate200, _Errors]: ...
    @_t.overload
    def delete_agent_environment_template(self, environment_template_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteAgentEnvironmentTemplate200, _HttpClientResponse], _Errors]: ...
    def delete_agent_environment_template(self, environment_template_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes reusable environment configuration and all confidential template inputs. See [reusing a hosted setup](https://developers.openai.com/api/docs/guides/agents-api/tools#reuse-a-hosted-plugin-setup)."""
        return self._json(_DELETE_AGENT_ENVIRONMENT_TEMPLATE, _c.encoded_path("/agents/environments/templates/{}", environment_template_id), None, None, include_response)

    @_t.overload
    def list_agent_sessions(self, *, params: _T.ListAgentSessionsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentSessions200, _Errors]: ...
    @_t.overload
    def list_agent_sessions(self, *, params: _T.ListAgentSessionsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentSessions200, _HttpClientResponse], _Errors]: ...
    def list_agent_sessions(self, *, params: _T.ListAgentSessionsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists managed agent sessions using ID-based pagination and the requested sort order. See [managing sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions/manage)."""
        return self._json(_LIST_AGENT_SESSIONS, "/agents/sessions", params, None, include_response)

    @_t.overload
    def create_agent_session(self, *, payload: _T.CreateAgentSessionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateAgentSession201, _Errors]: ...
    @_t.overload
    def create_agent_session(self, *, payload: _T.CreateAgentSessionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateAgentSession201, _HttpClientResponse], _Errors]: ...
    def create_agent_session(self, *, payload: _T.CreateAgentSessionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a managed agent session, optionally submits initial input, and returns the session or streams its events when stream is true. See [running sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions)."""
        return self._json(_CREATE_AGENT_SESSION, "/agents/sessions", None, _c.json_body(payload), include_response)

    def create_agent_session_sse(self, *, payload: _T.CreateAgentSessionRequestJson) -> _Stream[_sse.DataEvent[_T.CreateAgentSession201Sse], _SseErrors]:
        """Creates a managed agent session, optionally submits initial input, and returns the session or streams its events when stream is true. See [running sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions)."""
        return self._sse(_CREATE_AGENT_SESSION_SSE, "/agents/sessions", None, _c.json_body(payload), CreateAgentSession201Sse)

    @_t.overload
    def retrieve_agent_session(self, session_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveAgentSession200, _Errors]: ...
    @_t.overload
    def retrieve_agent_session(self, session_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveAgentSession200, _HttpClientResponse], _Errors]: ...
    def retrieve_agent_session(self, session_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves the current state of a managed agent session. See [managing sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions/manage)."""
        return self._json(_RETRIEVE_AGENT_SESSION, _c.encoded_path("/agents/sessions/{}", session_id), None, None, include_response)

    @_t.overload
    def update_agent_session(self, session_id: str, *, payload: _T.UpdateAgentSessionRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateAgentSession200, _Errors]: ...
    @_t.overload
    def update_agent_session(self, session_id: str, *, payload: _T.UpdateAgentSessionRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateAgentSession200, _HttpClientResponse], _Errors]: ...
    def update_agent_session(self, session_id: str, *, payload: _T.UpdateAgentSessionRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates session metadata, model, reasoning effort, or service tier. Model settings apply to subsequent turns. Omitted fields are unchanged. See [managing sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions/manage)."""
        return self._json(_UPDATE_AGENT_SESSION, _c.encoded_path("/agents/sessions/{}", session_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_agent_session(self, session_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteAgentSession200, _Errors]: ...
    @_t.overload
    def delete_agent_session(self, session_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteAgentSession200, _HttpClientResponse], _Errors]: ...
    def delete_agent_session(self, session_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Removes a managed agent session from the public API and returns a deletion confirmation. If backend execution has ended, deletion can cancel a still-open public turn and abandon unpublished outputs. Running execution must be cancelled first. Physical cleanup may continue asynchronously. See [managing sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions/manage)."""
        return self._json(_DELETE_AGENT_SESSION, _c.encoded_path("/agents/sessions/{}", session_id), None, None, include_response)

    @_t.overload
    def list_agent_session_artifacts(self, session_id: str, *, params: _T.ListAgentSessionArtifactsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentSessionArtifacts200, _Errors]: ...
    @_t.overload
    def list_agent_session_artifacts(self, session_id: str, *, params: _T.ListAgentSessionArtifactsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentSessionArtifacts200, _HttpClientResponse], _Errors]: ...
    def list_agent_session_artifacts(self, session_id: str, *, params: _T.ListAgentSessionArtifactsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists immutable artifacts published by completed hosted session turns. See [session artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files#openai-hosted-artifacts)."""
        return self._json(_LIST_AGENT_SESSION_ARTIFACTS, _c.encoded_path("/agents/sessions/{}/artifacts", session_id), params, None, include_response)

    @_t.overload
    def retrieve_agent_session_artifact(self, session_id: str, artifact_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveAgentSessionArtifact200, _Errors]: ...
    @_t.overload
    def retrieve_agent_session_artifact(self, session_id: str, artifact_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveAgentSessionArtifact200, _HttpClientResponse], _Errors]: ...
    def retrieve_agent_session_artifact(self, session_id: str, artifact_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves immutable metadata for one durable session artifact. See [session artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files#openai-hosted-artifacts)."""
        return self._json(_RETRIEVE_AGENT_SESSION_ARTIFACT, _c.encoded_path("/agents/sessions/{}/artifacts/{}", session_id, artifact_id), None, None, include_response)

    @_t.overload
    def delete_agent_session_artifact(self, session_id: str, artifact_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteAgentSessionArtifact200, _Errors]: ...
    @_t.overload
    def delete_agent_session_artifact(self, session_id: str, artifact_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteAgentSessionArtifact200, _HttpClientResponse], _Errors]: ...
    def delete_agent_session_artifact(self, session_id: str, artifact_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes an immutable session artifact without deleting its live environment file or original Files API object. See [session artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files#openai-hosted-artifacts)."""
        return self._json(_DELETE_AGENT_SESSION_ARTIFACT, _c.encoded_path("/agents/sessions/{}/artifacts/{}", session_id, artifact_id), None, None, include_response)

    @_t.overload
    def retrieve_agent_session_artifact_content(self, session_id: str, artifact_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[bytes, _Errors]: ...
    @_t.overload
    def retrieve_agent_session_artifact_content(self, session_id: str, artifact_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[bytes, _HttpClientResponse], _Errors]: ...
    def retrieve_agent_session_artifact_content(self, session_id: str, artifact_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Downloads immutable session artifact bytes after the execution environment expires. See [session artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files#openai-hosted-artifacts)."""
        return self._json(_RETRIEVE_AGENT_SESSION_ARTIFACT_CONTENT, _c.encoded_path("/agents/sessions/{}/artifacts/{}/content", session_id, artifact_id), None, None, include_response)

    def retrieve_agent_session_artifact_content_stream(self, session_id: str, artifact_id: str) -> _Stream[bytes, _HttpClientError]:
        """Downloads immutable session artifact bytes after the execution environment expires. See [session artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files#openai-hosted-artifacts)."""
        return self._binary(_RETRIEVE_AGENT_SESSION_ARTIFACT_CONTENT_STREAM, _c.encoded_path("/agents/sessions/{}/artifacts/{}/content", session_id, artifact_id), None, None)

    @_t.overload
    def list_agent_session_events(self, session_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def list_agent_session_events(self, session_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def list_agent_session_events(self, session_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Streams live events for an agent session. See [session events](https://developers.openai.com/api/docs/guides/agents-api/sessions/events)."""
        return self._json(_LIST_AGENT_SESSION_EVENTS, _c.encoded_path("/agents/sessions/{}/events", session_id), None, None, include_response)

    def list_agent_session_events_sse(self, session_id: str) -> _Stream[_sse.DataEvent[_T.ListAgentSessionEvents200Sse], _SseErrors]:
        """Streams live events for an agent session. See [session events](https://developers.openai.com/api/docs/guides/agents-api/sessions/events)."""
        return self._sse(_LIST_AGENT_SESSION_EVENTS_SSE, _c.encoded_path("/agents/sessions/{}/events", session_id), None, None, ListAgentSessionEvents200Sse)

    @_t.overload
    def create_agent_session_events(self, session_id: str, *, payload: _T.CreateAgentSessionEventsRequestJson, params: _T.CreateAgentSessionEventsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[None, _Errors]: ...
    @_t.overload
    def create_agent_session_events(self, session_id: str, *, payload: _T.CreateAgentSessionEventsRequestJson, params: _T.CreateAgentSessionEventsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[None, _HttpClientResponse], _Errors]: ...
    def create_agent_session_events(self, session_id: str, *, payload: _T.CreateAgentSessionEventsRequestJson, params: _T.CreateAgentSessionEventsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Submits message, cancellation, tool-result, or computer-use approval-response events to a managed agent session. Cancellation can recover a still-open turn whose backend execution has ended by marking it cancelled and abandoning unpublished outputs. Saved results, published files, and existing terminal outcomes are preserved. HTTP 202 confirms acceptance, not durable completion. See [session events](https://developers.openai.com/api/docs/guides/agents-api/sessions/events)."""
        return self._json(_CREATE_AGENT_SESSION_EVENTS, _c.encoded_path("/agents/sessions/{}/events", session_id), params, _c.json_body(payload), include_response)

    @_t.overload
    def list_agent_session_items(self, session_id: str, *, params: _T.ListAgentSessionItemsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentSessionItems200, _Errors]: ...
    @_t.overload
    def list_agent_session_items(self, session_id: str, *, params: _T.ListAgentSessionItemsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentSessionItems200, _HttpClientResponse], _Errors]: ...
    def list_agent_session_items(self, session_id: str, *, params: _T.ListAgentSessionItemsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists items produced by the session's root agent, including its interactions with subagents. Each subagent has its own item history. See [inspecting agent output](https://developers.openai.com/api/docs/guides/agents-api/observability)."""
        return self._json(_LIST_AGENT_SESSION_ITEMS, _c.encoded_path("/agents/sessions/{}/items", session_id), params, None, include_response)

    @_t.overload
    def list_agent_session_traces(self, session_id: str, *, params: _T.ListAgentSessionTracesParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentSessionTraces200, _Errors]: ...
    @_t.overload
    def list_agent_session_traces(self, session_id: str, *, params: _T.ListAgentSessionTracesParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentSessionTraces200, _HttpClientResponse], _Errors]: ...
    def list_agent_session_traces(self, session_id: str, *, params: _T.ListAgentSessionTracesParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists published root-turn traces as OTLP JSON, ordered by turn creation time and ID. Unpublished traces are skipped. Each page returns data available when read; it does not wait for late traces. Trace reads and the JSON response are limited to 16 MiB per request. If the limit is exceeded, request fewer traces."""
        return self._json(_LIST_AGENT_SESSION_TRACES, _c.encoded_path("/agents/sessions/{}/traces", session_id), params, None, include_response)

    @_t.overload
    def list_agent_session_turns(self, session_id: str, *, params: _T.ListAgentSessionTurnsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentSessionTurns200, _Errors]: ...
    @_t.overload
    def list_agent_session_turns(self, session_id: str, *, params: _T.ListAgentSessionTurnsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentSessionTurns200, _HttpClientResponse], _Errors]: ...
    def list_agent_session_turns(self, session_id: str, *, params: _T.ListAgentSessionTurnsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists turns by creation time and turn ID. The after cursor is exclusive in the selected order. See [session turns](https://developers.openai.com/api/docs/guides/agents-api/sessions/manage#inspect-session-turns)."""
        return self._json(_LIST_AGENT_SESSION_TURNS, _c.encoded_path("/agents/sessions/{}/turns", session_id), params, None, include_response)

    @_t.overload
    def retrieve_agent_session_turn(self, session_id: str, turn_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveAgentSessionTurn200, _Errors]: ...
    @_t.overload
    def retrieve_agent_session_turn(self, session_id: str, turn_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveAgentSessionTurn200, _HttpClientResponse], _Errors]: ...
    def retrieve_agent_session_turn(self, session_id: str, turn_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a turn's current status, timestamps, usage, and error. Returns 404 if the turn does not belong to the session. See [session turns](https://developers.openai.com/api/docs/guides/agents-api/sessions/manage#inspect-session-turns)."""
        return self._json(_RETRIEVE_AGENT_SESSION_TURN, _c.encoded_path("/agents/sessions/{}/turns/{}", session_id, turn_id), None, None, include_response)

    @_t.overload
    def list_agent_session_turn_items(self, session_id: str, turn_id: str, *, params: _T.ListAgentSessionTurnItemsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListAgentSessionTurnItems200, _Errors]: ...
    @_t.overload
    def list_agent_session_turn_items(self, session_id: str, turn_id: str, *, params: _T.ListAgentSessionTurnItemsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListAgentSessionTurnItems200, _HttpClientResponse], _Errors]: ...
    def list_agent_session_turn_items(self, session_id: str, turn_id: str, *, params: _T.ListAgentSessionTurnItemsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists items belonging to one root-agent turn, including its interactions with subagents. See [inspecting agent output](https://developers.openai.com/api/docs/guides/agents-api/observability)."""
        return self._json(_LIST_AGENT_SESSION_TURN_ITEMS, _c.encoded_path("/agents/sessions/{}/turns/{}/items", session_id, turn_id), params, None, include_response)

    @_t.overload
    def list_vaults(self, *, params: _T.ListVaultsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListVaults200, _Errors]: ...
    @_t.overload
    def list_vaults(self, *, params: _T.ListVaultsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListVaults200, _HttpClientResponse], _Errors]: ...
    def list_vaults(self, *, params: _T.ListVaultsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists vaults using ID-based pagination. See [vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults)."""
        return self._json(_LIST_VAULTS, "/vaults", params, None, include_response)

    @_t.overload
    def create_vault(self, *, payload: _T.CreateVaultRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVault201, _Errors]: ...
    @_t.overload
    def create_vault(self, *, payload: _T.CreateVaultRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVault201, _HttpClientResponse], _Errors]: ...
    def create_vault(self, *, payload: _T.CreateVaultRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a vault for the current project. See [vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults)."""
        return self._json(_CREATE_VAULT, "/vaults", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_vault(self, vault_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveVault200, _Errors]: ...
    @_t.overload
    def retrieve_vault(self, vault_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveVault200, _HttpClientResponse], _Errors]: ...
    def retrieve_vault(self, vault_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a vault by its ID. See [vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults)."""
        return self._json(_RETRIEVE_VAULT, _c.encoded_path("/vaults/{}", vault_id), None, None, include_response)

    @_t.overload
    def update_vault(self, vault_id: str, *, payload: _T.UpdateVaultRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateVault200, _Errors]: ...
    @_t.overload
    def update_vault(self, vault_id: str, *, payload: _T.UpdateVaultRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateVault200, _HttpClientResponse], _Errors]: ...
    def update_vault(self, vault_id: str, *, payload: _T.UpdateVaultRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates the name or metadata of an active vault. Omitted fields remain unchanged. See [vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults)."""
        return self._json(_UPDATE_VAULT, _c.encoded_path("/vaults/{}", vault_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_vault(self, vault_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteVault200, _Errors]: ...
    @_t.overload
    def delete_vault(self, vault_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteVault200, _HttpClientResponse], _Errors]: ...
    def delete_vault(self, vault_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a vault and all its credentials. See [vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults)."""
        return self._json(_DELETE_VAULT, _c.encoded_path("/vaults/{}", vault_id), None, None, include_response)

    @_t.overload
    def list_vault_credentials(self, vault_id: str, *, params: _T.ListVaultCredentialsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListVaultCredentials200, _Errors]: ...
    @_t.overload
    def list_vault_credentials(self, vault_id: str, *, params: _T.ListVaultCredentialsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListVaultCredentials200, _HttpClientResponse], _Errors]: ...
    def list_vault_credentials(self, vault_id: str, *, params: _T.ListVaultCredentialsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Lists a vault's credentials using ID-based pagination without returning secret values. See [vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults)."""
        return self._json(_LIST_VAULT_CREDENTIALS, _c.encoded_path("/vaults/{}/credentials", vault_id), params, None, include_response)

    @_t.overload
    def create_vault_credential(self, vault_id: str, *, payload: _T.CreateVaultCredentialRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateVaultCredential201, _Errors]: ...
    @_t.overload
    def create_vault_credential(self, vault_id: str, *, payload: _T.CreateVaultCredentialRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateVaultCredential201, _HttpClientResponse], _Errors]: ...
    def create_vault_credential(self, vault_id: str, *, payload: _T.CreateVaultCredentialRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a vault credential. Secret values are write-only and are never returned. See [vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults)."""
        return self._json(_CREATE_VAULT_CREDENTIAL, _c.encoded_path("/vaults/{}/credentials", vault_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_vault_credential(self, vault_id: str, credential_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveVaultCredential200, _Errors]: ...
    @_t.overload
    def retrieve_vault_credential(self, vault_id: str, credential_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveVaultCredential200, _HttpClientResponse], _Errors]: ...
    def retrieve_vault_credential(self, vault_id: str, credential_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves vault credential metadata without returning secret values. See [vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults)."""
        return self._json(_RETRIEVE_VAULT_CREDENTIAL, _c.encoded_path("/vaults/{}/credentials/{}", vault_id, credential_id), None, None, include_response)

    @_t.overload
    def rotate_vault_credential(self, vault_id: str, credential_id: str, *, payload: _T.RotateVaultCredentialRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.RotateVaultCredential200, _Errors]: ...
    @_t.overload
    def rotate_vault_credential(self, vault_id: str, credential_id: str, *, payload: _T.RotateVaultCredentialRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RotateVaultCredential200, _HttpClientResponse], _Errors]: ...
    def rotate_vault_credential(self, vault_id: str, credential_id: str, *, payload: _T.RotateVaultCredentialRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates credential metadata or rotates its write-only secret. See [vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults)."""
        return self._json(_ROTATE_VAULT_CREDENTIAL, _c.encoded_path("/vaults/{}/credentials/{}", vault_id, credential_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_vault_credential(self, vault_id: str, credential_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteVaultCredential200, _Errors]: ...
    @_t.overload
    def delete_vault_credential(self, vault_id: str, credential_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteVaultCredential200, _HttpClientResponse], _Errors]: ...
    def delete_vault_credential(self, vault_id: str, credential_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a vault credential. See [vaults](https://developers.openai.com/api/docs/guides/agents-api/tools/vaults)."""
        return self._json(_DELETE_VAULT_CREDENTIAL, _c.encoded_path("/vaults/{}/credentials/{}", vault_id, credential_id), None, None, include_response)

    @_t.overload
    def list_webhook_endpoints(self, *, params: _T.ListWebhookEndpointsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.ListWebhookEndpoints200, _Errors]: ...
    @_t.overload
    def list_webhook_endpoints(self, *, params: _T.ListWebhookEndpointsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListWebhookEndpoints200, _HttpClientResponse], _Errors]: ...
    def list_webhook_endpoints(self, *, params: _T.ListWebhookEndpointsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns webhook endpoints for the authenticated project in newest-first order."""
        return self._json(_LIST_WEBHOOK_ENDPOINTS, "/webhook_endpoints", params, None, include_response)

    @_t.overload
    def create_webhook_endpoint(self, *, payload: _T.CreateWebhookEndpointRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.CreateWebhookEndpoint200, _Errors]: ...
    @_t.overload
    def create_webhook_endpoint(self, *, payload: _T.CreateWebhookEndpointRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.CreateWebhookEndpoint200, _HttpClientResponse], _Errors]: ...
    def create_webhook_endpoint(self, *, payload: _T.CreateWebhookEndpointRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a webhook endpoint for the authenticated project."""
        return self._json(_CREATE_WEBHOOK_ENDPOINT, "/webhook_endpoints", None, _c.json_body(payload), include_response)

    @_t.overload
    def retrieve_webhook_endpoint(self, webhook_endpoint_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.RetrieveWebhookEndpoint200, _Errors]: ...
    @_t.overload
    def retrieve_webhook_endpoint(self, webhook_endpoint_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RetrieveWebhookEndpoint200, _HttpClientResponse], _Errors]: ...
    def retrieve_webhook_endpoint(self, webhook_endpoint_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a webhook endpoint for the authenticated project."""
        return self._json(_RETRIEVE_WEBHOOK_ENDPOINT, _c.encoded_path("/webhook_endpoints/{}", webhook_endpoint_id), None, None, include_response)

    @_t.overload
    def update_webhook_endpoint(self, webhook_endpoint_id: str, *, payload: _T.UpdateWebhookEndpointRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.UpdateWebhookEndpoint200, _Errors]: ...
    @_t.overload
    def update_webhook_endpoint(self, webhook_endpoint_id: str, *, payload: _T.UpdateWebhookEndpointRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.UpdateWebhookEndpoint200, _HttpClientResponse], _Errors]: ...
    def update_webhook_endpoint(self, webhook_endpoint_id: str, *, payload: _T.UpdateWebhookEndpointRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Updates a webhook endpoint for the authenticated project."""
        return self._json(_UPDATE_WEBHOOK_ENDPOINT, _c.encoded_path("/webhook_endpoints/{}", webhook_endpoint_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def delete_webhook_endpoint(self, webhook_endpoint_id: str, *, include_response: _t.Literal[False] = False) -> _Effect[_T.DeleteWebhookEndpoint200, _Errors]: ...
    @_t.overload
    def delete_webhook_endpoint(self, webhook_endpoint_id: str, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.DeleteWebhookEndpoint200, _HttpClientResponse], _Errors]: ...
    def delete_webhook_endpoint(self, webhook_endpoint_id: str, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a webhook endpoint for the authenticated project."""
        return self._json(_DELETE_WEBHOOK_ENDPOINT, _c.encoded_path("/webhook_endpoints/{}", webhook_endpoint_id), None, None, include_response)

    @_t.overload
    def rotate_webhook_endpoint_signing_secret(self, webhook_endpoint_id: str, *, payload: _T.RotateWebhookEndpointSigningSecretRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.RotateWebhookEndpointSigningSecret200, _Errors]: ...
    @_t.overload
    def rotate_webhook_endpoint_signing_secret(self, webhook_endpoint_id: str, *, payload: _T.RotateWebhookEndpointSigningSecretRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.RotateWebhookEndpointSigningSecret200, _HttpClientResponse], _Errors]: ...
    def rotate_webhook_endpoint_signing_secret(self, webhook_endpoint_id: str, *, payload: _T.RotateWebhookEndpointSigningSecretRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Rotates the signing secret for a webhook endpoint in the authenticated project."""
        return self._json(_ROTATE_WEBHOOK_ENDPOINT_SIGNING_SECRET, _c.encoded_path("/webhook_endpoints/{}/rotate_secret", webhook_endpoint_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def test_webhook_endpoint(self, webhook_endpoint_id: str, *, payload: _T.TestWebhookEndpointRequestJson, include_response: _t.Literal[False] = False) -> _Effect[_T.TestWebhookEndpoint200, _Errors]: ...
    @_t.overload
    def test_webhook_endpoint(self, webhook_endpoint_id: str, *, payload: _T.TestWebhookEndpointRequestJson, include_response: _t.Literal[True]) -> _Effect[tuple[_T.TestWebhookEndpoint200, _HttpClientResponse], _Errors]: ...
    def test_webhook_endpoint(self, webhook_endpoint_id: str, *, payload: _T.TestWebhookEndpointRequestJson, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Sends a sample event to a webhook endpoint for the authenticated project."""
        return self._json(_TEST_WEBHOOK_ENDPOINT, _c.encoded_path("/webhook_endpoints/{}/test", webhook_endpoint_id), None, _c.json_body(payload), include_response)

    @_t.overload
    def list_webhook_event_types(self, *, include_response: _t.Literal[False] = False) -> _Effect[_T.ListWebhookEventTypes200, _Errors]: ...
    @_t.overload
    def list_webhook_event_types(self, *, include_response: _t.Literal[True]) -> _Effect[tuple[_T.ListWebhookEventTypes200, _HttpClientResponse], _Errors]: ...
    def list_webhook_event_types(self, *, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns webhook event types visible to the authenticated project."""
        return self._json(_LIST_WEBHOOK_EVENT_TYPES, "/webhook_event_types", None, None, include_response)

    @_t.overload
    def beta_create_response(self, *, payload: _T.BetaCreateResponseRequestJson, params: _T.BetaCreateResponseParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BetaCreateResponse200, _Errors]: ...
    @_t.overload
    def beta_create_response(self, *, payload: _T.BetaCreateResponseRequestJson, params: _T.BetaCreateResponseParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BetaCreateResponse200, _HttpClientResponse], _Errors]: ...
    def beta_create_response(self, *, payload: _T.BetaCreateResponseRequestJson, params: _T.BetaCreateResponseParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Creates a model response. Provide [text](https://developers.openai.com/api/docs/guides/text) or
        [image](https://developers.openai.com/api/docs/guides/images-vision) inputs to generate [text](https://developers.openai.com/api/docs/guides/text)
        or [JSON](https://developers.openai.com/api/docs/guides/structured-outputs) outputs. Have the model call
        your own [custom code](https://developers.openai.com/api/docs/guides/function-calling) or use built-in
        [tools](https://developers.openai.com/api/docs/guides/tools) like [web search](https://developers.openai.com/api/docs/guides/tools-web-search)
        or [file search](https://developers.openai.com/api/docs/guides/tools-file-search) to use your own data
        as input for the model's response."""
        return self._json(_BETA_CREATE_RESPONSE, "/responses?beta=true", params, _c.json_body(payload), include_response)

    def beta_create_response_sse(self, *, payload: _T.BetaCreateResponseRequestJson, params: _T.BetaCreateResponseParams | None = None) -> _Stream[_sse.DataEvent[_T.BetaCreateResponse200Sse], _SseErrors]:
        """Creates a model response. Provide [text](https://developers.openai.com/api/docs/guides/text) or
        [image](https://developers.openai.com/api/docs/guides/images-vision) inputs to generate [text](https://developers.openai.com/api/docs/guides/text)
        or [JSON](https://developers.openai.com/api/docs/guides/structured-outputs) outputs. Have the model call
        your own [custom code](https://developers.openai.com/api/docs/guides/function-calling) or use built-in
        [tools](https://developers.openai.com/api/docs/guides/tools) like [web search](https://developers.openai.com/api/docs/guides/tools-web-search)
        or [file search](https://developers.openai.com/api/docs/guides/tools-file-search) to use your own data
        as input for the model's response."""
        return self._sse(_BETA_CREATE_RESPONSE_SSE, "/responses?beta=true", params, _c.json_body(payload), BetaCreateResponse200Sse)

    @_t.overload
    def beta_get_response(self, response_id: str, *, params: _T.BetaGetResponseParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BetaGetResponse200, _Errors]: ...
    @_t.overload
    def beta_get_response(self, response_id: str, *, params: _T.BetaGetResponseParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BetaGetResponse200, _HttpClientResponse], _Errors]: ...
    def beta_get_response(self, response_id: str, *, params: _T.BetaGetResponseParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Retrieves a model response with the given ID."""
        return self._json(_BETA_GET_RESPONSE, _c.encoded_path("/responses/{}?beta=true", response_id), params, None, include_response)

    @_t.overload
    def beta_delete_response(self, response_id: str, *, params: _T.BetaDeleteResponseParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BetaDeleteResponse200, _Errors]: ...
    @_t.overload
    def beta_delete_response(self, response_id: str, *, params: _T.BetaDeleteResponseParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BetaDeleteResponse200, _HttpClientResponse], _Errors]: ...
    def beta_delete_response(self, response_id: str, *, params: _T.BetaDeleteResponseParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Deletes a model response with the given ID."""
        return self._json(_BETA_DELETE_RESPONSE, _c.encoded_path("/responses/{}?beta=true", response_id), params, None, include_response)

    @_t.overload
    def beta_cancel_response(self, response_id: str, *, params: _T.BetaCancelResponseParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BetaCancelResponse200, _Errors]: ...
    @_t.overload
    def beta_cancel_response(self, response_id: str, *, params: _T.BetaCancelResponseParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BetaCancelResponse200, _HttpClientResponse], _Errors]: ...
    def beta_cancel_response(self, response_id: str, *, params: _T.BetaCancelResponseParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Cancels a model response with the given ID. Only responses created with
        the `background` parameter set to `true` can be cancelled.
        [Learn more](https://developers.openai.com/api/docs/guides/background)."""
        return self._json(_BETA_CANCEL_RESPONSE, _c.encoded_path("/responses/{}/cancel?beta=true", response_id), params, None, include_response)

    @_t.overload
    def beta_compactconversation(self, *, payload: _T.BetaCompactconversationRequestJson, params: _T.BetaCompactconversationParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BetaCompactconversation200, _Errors]: ...
    @_t.overload
    def beta_compactconversation(self, *, payload: _T.BetaCompactconversationRequestJson, params: _T.BetaCompactconversationParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BetaCompactconversation200, _HttpClientResponse], _Errors]: ...
    def beta_compactconversation(self, *, payload: _T.BetaCompactconversationRequestJson, params: _T.BetaCompactconversationParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Compact a conversation. Returns a compacted response object.
        
        Learn when and how to compact long-running conversations in the [conversation state guide](https://developers.openai.com/api/docs/guides/conversation-state#managing-the-context-window). For ZDR-compatible compaction details, see [Compaction (advanced)](https://developers.openai.com/api/docs/guides/conversation-state#compaction-advanced)."""
        return self._json(_BETA_COMPACTCONVERSATION, "/responses/compact?beta=true", params, _c.json_body(payload), include_response)

    @_t.overload
    def beta_list_input_items(self, response_id: str, *, params: _T.BetaListInputItemsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BetaListInputItems200, _Errors]: ...
    @_t.overload
    def beta_list_input_items(self, response_id: str, *, params: _T.BetaListInputItemsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BetaListInputItems200, _HttpClientResponse], _Errors]: ...
    def beta_list_input_items(self, response_id: str, *, params: _T.BetaListInputItemsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns a list of input items for a given response."""
        return self._json(_BETA_LIST_INPUT_ITEMS, _c.encoded_path("/responses/{}/input_items?beta=true", response_id), params, None, include_response)

    @_t.overload
    def beta_getinputtokencounts(self, *, payload: _T.BetaGetinputtokencountsRequestJson, params: _T.BetaGetinputtokencountsParams | None = None, include_response: _t.Literal[False] = False) -> _Effect[_T.BetaGetinputtokencounts200, _Errors]: ...
    @_t.overload
    def beta_getinputtokencounts(self, *, payload: _T.BetaGetinputtokencountsRequestJson, params: _T.BetaGetinputtokencountsParams | None = None, include_response: _t.Literal[True]) -> _Effect[tuple[_T.BetaGetinputtokencounts200, _HttpClientResponse], _Errors]: ...
    def beta_getinputtokencounts(self, *, payload: _T.BetaGetinputtokencountsRequestJson, params: _T.BetaGetinputtokencountsParams | None = None, include_response: bool = False) -> _Effect[_t.Any, _Errors]:
        """Returns input token counts of the request.
        
        Returns an object with `object` set to `response.input_tokens` and an `input_tokens` count."""
        return self._json(_BETA_GETINPUTTOKENCOUNTS, "/responses/input_tokens?beta=true", params, _c.json_body(payload), include_response)


def make(
    http_client: _HttpClientService[_HttpClientError],
    *,
    transform_client: _c.ClientTransform | None = None,
) -> OpenAiClient:
    """The client over ``http_client`` (requests carry relative paths:
    prepend the API's URL to the client). ``transform_client`` picks the
    client each operation runs on, per call."""
    return OpenAiClient(http_client, transform_client)


__all__ = ["OpenAiClient", "OpenAiClientError", "make"]
