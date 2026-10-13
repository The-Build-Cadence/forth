from __future__ import annotations

import os
import re
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from pgvector.django import HalfVectorField


def safe_upload_to(prefix: str, filename: str) -> str:
    _, ext = os.path.splitext(filename or '')
    suffix = (ext or '').lower()[:16]
    return f'{prefix}/{uuid.uuid4().hex}{suffix}'


def profile_document_upload_to(instance, filename):
    return safe_upload_to('profile_documents', filename)


def artifact_upload_to(instance, filename):
    stem = os.path.splitext(os.path.basename(filename or 'artifact'))[0]
    stem = re.sub(r'[^0-9A-Za-z]+', '-', stem).strip('-').lower()[:80] or 'artifact'
    _, ext = os.path.splitext(filename or '')
    return f'artifacts/{stem}-{uuid.uuid4().hex}{(ext or "").lower()[:16]}'


class OwnedModel(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CandidateProfile(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='candidate_profile')
    headline = models.CharField(max_length=220, blank=True)
    professional_summary = models.TextField(blank=True)
    target_roles = models.JSONField(default=list, blank=True)
    target_industries = models.JSONField(default=list, blank=True)
    location = models.CharField(max_length=220, blank=True)
    # Empty means legacy source contacts are preserved until the user configures them.
    resume_contact = models.JSONField(default=dict, blank=True)
    authorized_countries = models.JSONField(default=list, blank=True)
    work_modes = models.JSONField(default=list, blank=True)
    employment_types = models.JSONField(default=list, blank=True)
    minimum_compensation = models.PositiveIntegerField(null=True, blank=True)
    compensation_currency = models.CharField(max_length=8, default='CAD')
    # Raw evidence score required before Forth treats a role as ready to apply.
    # The UI presents a calibrated companion score alongside this value.
    minimum_match_score = models.PositiveSmallIntegerField(
        default=50,
        validators=[MinValueValidator(1), MaxValueValidator(99)],
    )
    excluded_companies = models.JSONField(default=list, blank=True)
    completeness = models.PositiveSmallIntegerField(default=0)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    onboarding_state = models.JSONField(default=dict, blank=True)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    semantic_embedding = HalfVectorField(dimensions=3072, null=True, blank=True)
    embedding_model = models.CharField(max_length=120, blank=True)
    embedding_provider = models.CharField(max_length=32, blank=True)
    embedding_content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    embedding_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.headline or f'Candidate profile for {self.owner}'


class OnboardingResponse(OwnedModel):
    """Durable, replayable memory for one Profile Steward interview turn."""

    question_id = models.CharField(max_length=120)
    target = models.CharField(max_length=48, db_index=True)
    question = models.JSONField(default=dict, blank=True)
    answer = models.JSONField(default=dict, blank=True)
    skipped = models.BooleanField(default=False)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['owner', 'question_id'], name='unique_owner_onboarding_question'),
        ]
        indexes = [models.Index(fields=['owner', 'target'])]

    def __str__(self) -> str:
        return f'{self.target}: {self.question_id}'


class CandidatePreference(OwnedModel):
    IMPORTANCE_CHOICES = [
        ('must', 'Must have'),
        ('strong', 'Strong preference'),
        ('flexible', 'Flexible'),
        ('avoid', 'Avoid'),
    ]

    category = models.CharField(max_length=48, db_index=True)
    label = models.CharField(max_length=220)
    value = models.JSONField(default=dict, blank=True)
    importance = models.CharField(max_length=16, choices=IMPORTANCE_CHOICES, default='flexible', db_index=True)
    verified_by_user = models.BooleanField(default=False, db_index=True)
    rationale = models.TextField(blank=True)

    class Meta:
        ordering = ['category', 'label', 'id']
        indexes = [models.Index(fields=['owner', 'category', 'importance'])]

    def __str__(self) -> str:
        return self.label


class ProfileDocument(OwnedModel):
    KIND_CHOICES = [
        ('brave', 'Brave web discovery'),
        ('resume', 'Resume'),
        ('note', 'Note'),
        ('conversation', 'Conversation'),
        ('profile', 'Profile'),
        ('project', 'Project'),
        ('review', 'Review'),
    ]
    STATUS_CHOICES = [
        ('new', 'New'),
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
    ]

    kind = models.CharField(max_length=24, choices=KIND_CHOICES, default='note', db_index=True)
    title = models.CharField(max_length=220)
    upload = models.FileField(upload_to=profile_document_upload_to, blank=True)
    raw_text = models.TextField(blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='new', db_index=True)
    status_message = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-updated_at', '-id']
        indexes = [
            models.Index(fields=['owner', 'kind']),
            models.Index(fields=['owner', 'status']),
        ]

    def __str__(self) -> str:
        return self.title


class ProfileChunk(OwnedModel):
    document = models.ForeignKey(ProfileDocument, on_delete=models.CASCADE, related_name='chunks')
    text = models.TextField()
    token_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['document_id', 'id']
        indexes = [models.Index(fields=['owner', 'document'])]


class ProfileFact(OwnedModel):
    FACT_CHOICES = [
        ('skill', 'Skill'),
        ('achievement', 'Achievement'),
        ('role', 'Role'),
        ('project', 'Project'),
        ('metric', 'Metric'),
        ('preference', 'Preference'),
        ('constraint', 'Constraint'),
        ('education', 'Education'),
    ]

    fact_type = models.CharField(max_length=32, choices=FACT_CHOICES, default='achievement', db_index=True)
    title = models.CharField(max_length=220)
    statement = models.TextField()
    normalized_value = models.CharField(max_length=220, blank=True)
    confidence = models.CharField(max_length=24, default='medium')
    source_document = models.ForeignKey(ProfileDocument, null=True, blank=True, on_delete=models.SET_NULL, related_name='facts')
    source_chunk = models.ForeignKey(ProfileChunk, null=True, blank=True, on_delete=models.SET_NULL, related_name='facts')
    verified_by_user = models.BooleanField(default=False, db_index=True)
    semantic_embedding = HalfVectorField(dimensions=3072, null=True, blank=True)
    embedding_model = models.CharField(max_length=120, blank=True)
    embedding_provider = models.CharField(max_length=32, blank=True)
    embedding_content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    embedding_updated_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    lifecycle = models.CharField(max_length=24, default='proposed', db_index=True)
    evidence_quote = models.TextField(blank=True)
    strength = models.CharField(max_length=24, default='working')
    started_on = models.DateField(null=True, blank=True)
    ended_on = models.DateField(null=True, blank=True)
    user_notes = models.TextField(blank=True)

    class Meta:
        ordering = ['fact_type', 'title', '-id']
        indexes = [
            models.Index(fields=['owner', 'fact_type']),
            models.Index(fields=['owner', 'verified_by_user']),
        ]

    def __str__(self) -> str:
        return self.title


class JobSource(OwnedModel):
    KIND_CHOICES = [
        ('brave', 'Brave web discovery'),
    ]

    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default='brave', db_index=True)
    name = models.CharField(max_length=220)
    config = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True, db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=32, blank=True)
    last_message = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['name', 'id']
        indexes = [models.Index(fields=['owner', 'enabled'])]

    def __str__(self) -> str:
        return self.name


class SourceRun(OwnedModel):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('succeeded', 'Succeeded'),
        ('partial', 'Partial'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    source = models.ForeignKey(JobSource, on_delete=models.CASCADE, related_name='runs')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='queued', db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    discovered_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    cursor = models.JSONField(default=dict, blank=True)
    log = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['owner', 'source', 'status'])]


class SourceSearchQuery(OwnedModel):
    """Durable memory of Brave query combinations tried for a source."""

    source = models.ForeignKey(JobSource, on_delete=models.CASCADE, related_name='search_queries')
    query_hash = models.CharField(max_length=64)
    query = models.CharField(max_length=500)
    components = models.JSONField(default=dict, blank=True)
    search_count = models.PositiveIntegerField(default=0)
    last_searched_at = models.DateTimeField(null=True, blank=True)
    last_result_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['search_count', 'last_searched_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['source', 'query_hash'], name='unique_source_search_query_hash'),
        ]
        indexes = [
            models.Index(fields=['source', 'search_count', 'last_searched_at'], name='core_source_source__b80936_idx'),
            models.Index(fields=['owner', 'source'], name='core_source_owner_i_dfb0cf_idx'),
        ]


class JobPosting(OwnedModel):
    REMOTE_CHOICES = [
        ('unknown', 'Unknown'),
        ('remote', 'Remote'),
        ('hybrid', 'Hybrid'),
        ('onsite', 'On-site'),
    ]

    source = models.ForeignKey(JobSource, null=True, blank=True, on_delete=models.SET_NULL, related_name='jobs')
    title = models.CharField(max_length=240)
    company = models.CharField(max_length=220, blank=True)
    location = models.CharField(max_length=220, blank=True)
    remote_policy = models.CharField(max_length=24, choices=REMOTE_CHOICES, default='unknown', db_index=True)
    seniority = models.CharField(max_length=120, blank=True)
    compensation = models.CharField(max_length=160, blank=True)
    description_text = models.TextField()
    extracted_json = models.JSONField(default=dict, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    application_url = models.URLField(max_length=1000, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    semantic_embedding = HalfVectorField(dimensions=3072, null=True, blank=True)
    embedding_model = models.CharField(max_length=120, blank=True)
    embedding_provider = models.CharField(max_length=32, blank=True)
    embedding_content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    embedding_updated_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, default='new', db_index=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    discovered_at = models.DateTimeField(auto_now_add=True)
    canonical_url = models.URLField(max_length=1000, blank=True)
    source_external_id = models.CharField(max_length=220, blank=True, db_index=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    freshness_status = models.CharField(max_length=24, default='fresh', db_index=True)

    class Meta:
        ordering = ['-discovered_at', '-id']
        indexes = [
            models.Index(fields=['owner', 'status']),
            models.Index(fields=['owner', 'remote_policy']),
            models.Index(fields=['owner', 'company']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['owner', 'content_hash'], name='core_jobposting_owner_content_hash_uniq'),
        ]

    def __str__(self) -> str:
        company = f' at {self.company}' if self.company else ''
        return f'{self.title}{company}'


class JobPostingVersion(OwnedModel):
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveIntegerField(default=1)
    content_hash = models.CharField(max_length=64, db_index=True)
    description_text = models.TextField()
    extracted_json = models.JSONField(default=dict, blank=True)
    source_payload = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField()
    is_current = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ['job_id', '-version']
        constraints = [
            models.UniqueConstraint(fields=['job', 'version'], name='core_jobversion_job_version_uniq'),
            models.UniqueConstraint(fields=['job', 'content_hash'], name='core_jobversion_job_hash_uniq'),
        ]


class JobRequirement(OwnedModel):
    KIND_CHOICES = [
        ('required', 'Required'),
        ('preferred', 'Preferred'),
        ('responsibility', 'Responsibility'),
        ('credential', 'Credential'),
    ]

    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name='requirements')
    kind = models.CharField(max_length=24, choices=KIND_CHOICES, default='required', db_index=True)
    category = models.CharField(max_length=48, default='other', db_index=True)
    text = models.TextField()
    normalized_value = models.CharField(max_length=220, blank=True)
    is_hard = models.BooleanField(default=False, db_index=True)
    weight = models.PositiveSmallIntegerField(default=50)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-is_hard', 'kind', '-weight', 'id']
        indexes = [models.Index(fields=['owner', 'job', 'kind'])]


class JobMatch(OwnedModel):
    job = models.OneToOneField(JobPosting, on_delete=models.CASCADE, related_name='match')
    score = models.PositiveSmallIntegerField(default=0, db_index=True)
    hard_filter_status = models.CharField(max_length=32, default='pass')
    explanation_json = models.JSONField(default=dict, blank=True)
    missing_requirements = models.JSONField(default=list, blank=True)
    supporting_facts = models.JSONField(default=list, blank=True)
    confidence = models.CharField(max_length=24, default='medium')
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-score', '-computed_at']
        indexes = [
            models.Index(fields=['owner', '-score']),
            models.Index(fields=['owner', 'confidence']),
        ]

    def __str__(self) -> str:
        return f'{self.job}: {self.score}'


class MatchSignal(OwnedModel):
    SIGNAL_CHOICES = [
        ('eligibility', 'Eligibility'),
        ('skills', 'Skills'),
        ('evidence', 'Experience evidence'),
        ('semantic', 'Semantic fit'),
        ('direction', 'Role direction'),
        ('domain', 'Domain relevance'),
        ('logistics', 'Logistics'),
        ('risk', 'Risk'),
    ]

    match = models.ForeignKey(JobMatch, on_delete=models.CASCADE, related_name='signals')
    kind = models.CharField(max_length=24, choices=SIGNAL_CHOICES, db_index=True)
    label = models.CharField(max_length=220)
    score = models.PositiveSmallIntegerField(default=0)
    weight = models.PositiveSmallIntegerField(default=0)
    explanation = models.TextField(blank=True)
    evidence = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-weight', 'kind', 'id']
        indexes = [models.Index(fields=['owner', 'match', 'kind'])]


class ProfileImprovementProposal(OwnedModel):
    STATUS_CHOICES = [
        ('pending', 'Pending review'),
        ('applied', 'Applied'),
        ('rejected', 'Rejected'),
        ('superseded', 'Superseded'),
    ]

    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name='profile_improvement_proposals')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='pending', db_index=True)
    source_score = models.PositiveSmallIntegerField(default=0)
    suggestions = models.JSONField(default=list, blank=True)
    decision = models.JSONField(default=dict, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['owner', 'job', 'status'])]

    def __str__(self) -> str:
        return f'Profile improvements for {self.job} ({self.status})'


class Resume(OwnedModel):
    KIND_CHOICES = [
        ('canonical', 'Canonical'),
        ('tailored', 'Tailored'),
    ]

    kind = models.CharField(max_length=24, choices=KIND_CHOICES, default='canonical', db_index=True)
    title = models.CharField(max_length=220)
    content_markdown = models.TextField()
    content_json = models.JSONField(default=dict, blank=True)
    parent_resume = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='variants')
    target_job = models.ForeignKey(JobPosting, null=True, blank=True, on_delete=models.SET_NULL, related_name='resumes')
    validation = models.JSONField(default=dict, blank=True)
    approved = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['-updated_at', '-id']
        indexes = [
            models.Index(fields=['owner', 'kind']),
            models.Index(fields=['owner', 'approved']),
        ]

    def __str__(self) -> str:
        return self.title


class ResumeClaim(OwnedModel):
    SUPPORT_CHOICES = [
        ('supported', 'Supported'),
        ('user_confirmed', 'User Confirmed'),
        ('unsupported', 'Unsupported'),
    ]

    resume = models.ForeignKey(Resume, on_delete=models.CASCADE, related_name='claims')
    text = models.TextField()
    profile_fact = models.ForeignKey(ProfileFact, null=True, blank=True, on_delete=models.SET_NULL, related_name='resume_claims')
    support_status = models.CharField(max_length=32, choices=SUPPORT_CHOICES, default='unsupported', db_index=True)

    class Meta:
        ordering = ['resume_id', 'id']


class CoverLetter(OwnedModel):
    title = models.CharField(max_length=220)
    target_job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name='cover_letters')
    content_markdown = models.TextField()
    content_json = models.JSONField(default=dict, blank=True)
    validation = models.JSONField(default=dict, blank=True)
    approved = models.BooleanField(default=False, db_index=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-updated_at', '-id']
        indexes = [models.Index(fields=['owner', 'target_job', 'approved'])]


class Application(OwnedModel):
    STATUS_CHOICES = [
        ('review', 'Review'),
        ('discovered', 'Discovered'),
        ('saved', 'Saved'),
        ('approved', 'Approved to Prepare'),
        ('preparing', 'Preparing Materials'),
        ('materials_ready', 'Materials Ready'),
        ('resume_ready', 'Resume Ready'),
        ('applied', 'Applied'),
        ('follow_up_due', 'Follow-Up Due'),
        ('recruiter_screen', 'Recruiter Screen'),
        ('technical_screen', 'Technical Screen'),
        ('onsite_final', 'Onsite / Final'),
        ('offer', 'Offer'),
        ('rejected', 'Rejected'),
        ('archived', 'Archived'),
    ]

    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name='applications')
    application_form_url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='saved', db_index=True)
    resume = models.ForeignKey(Resume, null=True, blank=True, on_delete=models.SET_NULL, related_name='applications')
    applied_at = models.DateTimeField(null=True, blank=True)
    follow_up_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    contact_name = models.CharField(max_length=160, blank=True)
    contact_email = models.EmailField(blank=True)

    class Meta:
        ordering = ['-updated_at', '-id']
        indexes = [
            models.Index(fields=['owner', 'status']),
            models.Index(fields=['owner', 'follow_up_at']),
        ]

    def __str__(self) -> str:
        return f'{self.job} ({self.status})'

    def save(self, *args, **kwargs):
        if not self.application_form_url and self.job_id:
            job = self.job
            self.application_form_url = job.application_url or job.source_url
        super().save(*args, **kwargs)


class ApplicationEvent(OwnedModel):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=64, db_index=True)
    happened_at = models.DateTimeField()
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-happened_at', '-id']
        indexes = [models.Index(fields=['application', 'event_type'])]


class Artifact(OwnedModel):
    KIND_CHOICES = [
        ('resume_pdf', 'Resume PDF'),
        ('resume_docx', 'Resume DOCX'),
        ('resume_markdown', 'Resume Markdown'),
        ('cover_letter', 'Cover Letter'),
        ('cover_letter_pdf', 'Cover Letter PDF'),
        ('cover_letter_html', 'Cover Letter HTML'),
        ('resume_html', 'Resume HTML'),
        ('note', 'Note'),
        ('export', 'Export'),
    ]

    application = models.ForeignKey(Application, null=True, blank=True, on_delete=models.SET_NULL, related_name='artifacts')
    resume = models.ForeignKey(Resume, null=True, blank=True, on_delete=models.SET_NULL, related_name='artifacts')
    cover_letter = models.ForeignKey(CoverLetter, null=True, blank=True, on_delete=models.SET_NULL, related_name='artifacts')
    kind = models.CharField(max_length=40, choices=KIND_CHOICES, default='note', db_index=True)
    title = models.CharField(max_length=220)
    file = models.FileField(upload_to=artifact_upload_to, blank=True)
    content_text = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    mime_type = models.CharField(max_length=120, blank=True)
    approved = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['owner', 'kind'])]


class ConversationThread(OwnedModel):
    title = models.CharField(max_length=220, default='Forth concierge')
    status = models.CharField(max_length=24, default='active', db_index=True)
    context = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-updated_at', '-id']


class ConversationMessage(OwnedModel):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
        ('tool', 'Tool'),
    ]

    thread = models.ForeignKey(ConversationThread, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, db_index=True)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [models.Index(fields=['owner', 'thread', 'created_at'])]


class AgentRun(OwnedModel):
    AGENT_CHOICES = [
        ('concierge', 'Forth Concierge'),
        ('profile', 'Profile Steward'),
        ('sourcing', 'Sourcing Scout'),
        ('matching', 'Match Analyst'),
        ('application', 'Application Coach'),
        ('documents', 'Document Tailor'),
    ]
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('waiting_approval', 'Waiting for approval'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    thread = models.ForeignKey(ConversationThread, null=True, blank=True, on_delete=models.SET_NULL, related_name='runs')
    agent = models.CharField(max_length=24, choices=AGENT_CHOICES, db_index=True)
    objective = models.TextField()
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='queued', db_index=True)
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=128, blank=True, db_index=True)
    celery_task_id = models.CharField(max_length=80, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    model = models.CharField(max_length=80, blank=True)
    usage = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['owner', 'agent', 'status'])]


class AgentStep(OwnedModel):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name='steps')
    sequence = models.PositiveIntegerField(default=1)
    kind = models.CharField(max_length=32, default='tool')
    name = models.CharField(max_length=120)
    status = models.CharField(max_length=24, default='running', db_index=True)
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['run_id', 'sequence', 'id']
        constraints = [models.UniqueConstraint(fields=['run', 'sequence'], name='core_agentstep_run_sequence_uniq')]


class ApprovalRequest(OwnedModel):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    run = models.ForeignKey(AgentRun, null=True, blank=True, on_delete=models.SET_NULL, related_name='approvals')
    kind = models.CharField(max_length=48, db_index=True)
    title = models.CharField(max_length=220)
    prompt = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default='pending', db_index=True)
    response = models.JSONField(default=dict, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['owner', 'status', 'kind'])]
