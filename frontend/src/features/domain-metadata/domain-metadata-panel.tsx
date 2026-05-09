import { useState } from "react";
import { Braces, Loader2, Wand2 } from "lucide-react";

import { apiClient } from "../../api/client";
import type {
  DomainMetadata,
  DomainProfileOut,
  IndexDocumentIn,
  ParserMode,
} from "../../api/generated";
import { Button } from "../../components/ui/button";

const parserOptions: Array<{ value: ParserMode; label: string }> = [
  { value: "local_fallback", label: "Local fallback" },
  { value: "mineru_strict", label: "MinerU strict" },
  { value: "mineru_with_fallback", label: "MinerU with fallback" },
];

const sampleCustomJson = {
  source_system: "library_upload",
  audience: "research",
  citation_style: "surah_ayah",
  extraction_notes: "Preserve Arabic text, English translation, and verse references.",
  review: {
    owner: "domain-expert",
    priority: "high",
  },
};

type MetadataChangeField =
  | "domain"
  | "document_type"
  | "language"
  | "authority"
  | "source"
  | "collection"
  | "citation_style"
  | "expected_structure"
  | "reference_pattern"
  | "script"
  | "content_role"
  | "tags"
  | "metadata_sources"
  | "custom_json";

type MetadataChange = {
  field: MetadataChangeField;
  label: string;
  summary: string;
  details?: string[];
};

export function DomainMetadataPanel({
  profiles,
  value,
  onChange,
  disabled = false,
  suggestContext,
  onValidityChange,
}: {
  profiles: DomainProfileOut[];
  value: IndexDocumentIn;
  onChange: (value: IndexDocumentIn) => void;
  disabled?: boolean;
  suggestContext?: {
    filename: string;
    content_type: string;
    file?: File;
  };
  onValidityChange?: (isValid: boolean) => void;
}) {
  const metadata = value.domain_metadata ?? {};
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [customJsonDraft, setCustomJsonDraft] = useState<string | null>(null);
  const [customJsonError, setCustomJsonError] = useState("");
  const [showCustomJsonSample, setShowCustomJsonSample] = useState(false);
  const [referenceSchemaState, setReferenceSchemaState] = useState<
    "idle" | "loading" | "error"
  >("idle");
  const [suggestState, setSuggestState] = useState<"idle" | "loading" | "error">("idle");
  const [autosuggestChanges, setAutosuggestChanges] = useState<MetadataChange[]>([]);
  const [autosuggestBaseline, setAutosuggestBaseline] = useState<DomainMetadata | null>(null);
  const [autosuggestMetadata, setAutosuggestMetadata] = useState<DomainMetadata | null>(null);
  const [autosuggestEvidence, setAutosuggestEvidence] = useState<{
    confidence: number;
    evidencePages: number[];
    rationale: string;
    warnings: string[];
  } | null>(null);
  const customJsonText =
    customJsonDraft ?? JSON.stringify(metadata.custom_json ?? {}, null, 2);
  const sampleCustomJsonText = JSON.stringify(sampleCustomJson, null, 2);
  const setMetadata = (patch: DomainMetadata) => {
    const currentMetadata = autosuggestMetadata ?? metadata;
    const nextMetadata = { ...currentMetadata, ...patch };
    setAutosuggestMetadata((current) => (current ? nextMetadata : current));
    onChange({ ...value, domain_metadata: nextMetadata });
  };
  const hasAutosuggestChange = (field: MetadataChangeField) =>
    autosuggestChanges.some((change) => change.field === field);
  const clearChangedField = (field: MetadataChangeField) => {
    setAutosuggestChanges((changes) => changes.filter((change) => change.field !== field));
  };
  const changedFieldProps = (field: MetadataChangeField) =>
    hasAutosuggestChange(field) ? { "data-autosuggest-changed": "true" } : {};

  const suggest = async () => {
    if (!suggestContext?.file) {
      return;
    }
    setSuggestState("loading");
    try {
      const response = await apiClient.suggestDomainMetadata({
        file: suggestContext.file,
        profile_id: selectedProfileId || null,
      });
      const nextMetadata = response.domain_metadata;
      setAutosuggestBaseline(metadata);
      setAutosuggestMetadata(nextMetadata);
      setAutosuggestChanges(buildMetadataChangeSet(metadata, nextMetadata));
      setAutosuggestEvidence({
        confidence: response.confidence,
        evidencePages: response.evidence_pages,
        rationale: response.rationale,
        warnings: response.warnings,
      });
      onChange({ ...value, domain_metadata: nextMetadata });
      setCustomJsonDraft(JSON.stringify(nextMetadata.custom_json ?? {}, null, 2));
      setCustomJsonError("");
      onValidityChange?.(true);
      setSuggestState("idle");
    } catch {
      setSuggestState("error");
    }
  };
  const acceptAutosuggestField = (field: MetadataChangeField) => {
    clearChangedField(field);
  };
  const rejectAutosuggestField = (field: MetadataChangeField) => {
    if (!autosuggestBaseline) {
      return;
    }
    const nextMetadata: DomainMetadata = { ...(autosuggestMetadata ?? metadata) };
    if (field === "tags") {
      nextMetadata.tags = autosuggestBaseline.tags ?? [];
    } else if (field === "metadata_sources") {
      nextMetadata.metadata_sources = autosuggestBaseline.metadata_sources ?? [];
    } else if (field === "custom_json") {
      nextMetadata.custom_json = autosuggestBaseline.custom_json ?? {};
      setCustomJsonDraft(JSON.stringify(nextMetadata.custom_json, null, 2));
      setCustomJsonError("");
      onValidityChange?.(true);
    } else {
      const key = field as keyof DomainMetadata;
      nextMetadata[key] = autosuggestBaseline[key] as never;
    }
    setAutosuggestMetadata(nextMetadata);
    clearChangedField(field);
    onChange({ ...value, domain_metadata: nextMetadata });
  };
  const applyCustomJson = (nextValue: string) => {
    setCustomJsonDraft(nextValue);
    try {
      const parsed = JSON.parse(nextValue || "{}");
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setCustomJsonError("Custom JSON must be an object.");
        onValidityChange?.(false);
        return;
      }
      setCustomJsonError("");
      onValidityChange?.(true);
      clearChangedField("custom_json");
      setMetadata({ custom_json: parsed as Record<string, unknown> });
    } catch {
      setCustomJsonError("Custom JSON must be valid JSON.");
      onValidityChange?.(false);
    }
  };
  const insertReferenceSchema = async () => {
    setReferenceSchemaState("loading");
    let current: Record<string, unknown>;
    try {
      const parsed = JSON.parse(customJsonText || "{}");
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setCustomJsonError("Custom JSON must be an object.");
        onValidityChange?.(false);
        setReferenceSchemaState("idle");
        return;
      }
      current = parsed as Record<string, unknown>;
    } catch {
      setCustomJsonError("Custom JSON must be valid JSON.");
      onValidityChange?.(false);
      setReferenceSchemaState("idle");
      return;
    }

    try {
      const response = await apiClient.getReferenceJsonExample();
      const merged = mergeJsonObjects(response.custom_json, current);
      setCustomJsonDraft(JSON.stringify(merged, null, 2));
      setCustomJsonError("");
      setReferenceSchemaState("idle");
      onValidityChange?.(true);
      clearChangedField("custom_json");
      onChange({ ...value, domain_metadata: { ...metadata, custom_json: merged } });
    } catch {
      setReferenceSchemaState("error");
    }
  };

  return (
    <section className="rounded-md border border-[#d6dde1] bg-white p-4">
      {autosuggestChanges.length > 0 || autosuggestEvidence ? (
        <div className="mb-3 rounded-md border border-[#9ccbd8] bg-[#edf7fa] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-[#1f2933]">
              {autosuggestChanges.length > 0
                ? "Auto-suggest updated metadata"
                : "Auto-suggest reviewed metadata"}
            </p>
            <p className="text-xs font-medium text-[#176b87]">
              {autosuggestChanges.length}{" "}
              {autosuggestChanges.length === 1 ? "field changed" : "fields changed"}
            </p>
          </div>
          {autosuggestChanges.length > 0 ? (
            <dl className="mt-2 grid gap-1.5 text-xs text-[#3a4a53]">
              {autosuggestChanges.map((change) => (
                <div key={change.field} className="grid gap-1 sm:grid-cols-[150px_minmax(0,1fr)]">
                  <dt className="font-semibold">{change.label}</dt>
                  <dd className="min-w-0 break-words">
                    <span>{change.summary}</span>
                    <div className="mt-1 flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => acceptAutosuggestField(change.field)}
                      >
                        Accept {change.label}
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => rejectAutosuggestField(change.field)}
                      >
                        Reject {change.label}
                      </Button>
                    </div>
                    {change.details?.length ? (
                      <ul className="mt-1 grid gap-0.5">
                        {change.details.map((detail) => (
                          <li key={detail}>{detail}</li>
                        ))}
                      </ul>
                    ) : null}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
          {autosuggestEvidence ? (
            <div className="mt-2 rounded border border-[#cfe3ea] bg-white/70 p-2 text-xs text-[#3a4a53]">
              <p>
                Confidence {Math.round(autosuggestEvidence.confidence * 100)}%
                {autosuggestEvidence.evidencePages.length > 0
                  ? ` from pages ${autosuggestEvidence.evidencePages.join(", ")}`
                  : ""}
              </p>
              {autosuggestEvidence.rationale ? <p>{autosuggestEvidence.rationale}</p> : null}
              {autosuggestEvidence.warnings.map((warning) => (
                <p key={warning}>{warning}</p>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium text-[#3a4a53]">
          <span className="mb-1.5 block">Parser</span>
          <select
            aria-label="Parser"
            className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
            value={value.parser_mode ?? "local_fallback"}
            disabled={disabled}
            onChange={(event) =>
              onChange({ ...value, parser_mode: event.target.value as ParserMode })
            }
          >
            {parserOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <div className="text-sm font-medium text-[#3a4a53]">
          <span className="mb-1.5 block">Domain profile</span>
          <select
            aria-label="Domain profile"
            className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
            disabled={disabled}
            value={selectedProfileId}
            onChange={(event) => {
              setSelectedProfileId(event.target.value);
              const profile = profiles.find((item) => item.id === event.target.value);
              if (profile) {
                setCustomJsonDraft(JSON.stringify(profile.metadata.custom_json ?? {}, null, 2));
                onChange({ ...value, domain_metadata: profile.metadata });
                setAutosuggestChanges([]);
                setAutosuggestBaseline(null);
                setAutosuggestMetadata(null);
                setAutosuggestEvidence(null);
                setCustomJsonError("");
                onValidityChange?.(true);
              }
            }}
          >
            <option value="">Choose profile</option>
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name}
              </option>
            ))}
          </select>
          {suggestContext ? (
            <div className="mt-2 flex justify-end">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={disabled || suggestState === "loading" || !suggestContext.file}
                onClick={() => void suggest()}
              >
                {suggestState === "loading" ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Wand2 className="h-4 w-4" aria-hidden="true" />
                )}
                Auto-suggest
              </Button>
            </div>
          ) : null}
        </div>
        <TextField
          label="Domain"
          value={metadata.domain ?? ""}
          disabled={disabled}
          changed={hasAutosuggestChange("domain")}
          onChange={(domain) => {
            clearChangedField("domain");
            setMetadata({ domain });
          }}
        />
        <TextField
          label="Document type"
          value={metadata.document_type ?? ""}
          disabled={disabled}
          changed={hasAutosuggestChange("document_type")}
          onChange={(document_type) => {
            clearChangedField("document_type");
            setMetadata({ document_type });
          }}
        />
        <TextField
          label="Language"
          value={metadata.language ?? ""}
          disabled={disabled}
          changed={hasAutosuggestChange("language")}
          onChange={(language) => {
            clearChangedField("language");
            setMetadata({ language });
          }}
        />
        <TextField
          label="Collection"
          value={metadata.collection ?? ""}
          disabled={disabled}
          changed={hasAutosuggestChange("collection")}
          onChange={(collection) => {
            clearChangedField("collection");
            setMetadata({ collection });
          }}
        />
        <TextField
          label="Tags"
          value={(metadata.tags ?? []).join(", ")}
          disabled={disabled}
          changed={hasAutosuggestChange("tags")}
          onChange={(tags) => {
            clearChangedField("tags");
            setMetadata({ tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean) });
          }}
        />
        <div
          className={
            hasAutosuggestChange("custom_json")
              ? "rounded-md border border-[#9ccbd8] bg-[#f3fafc] p-2 text-sm font-medium text-[#3a4a53] sm:col-span-2"
              : "text-sm font-medium text-[#3a4a53] sm:col-span-2"
          }
          {...changedFieldProps("custom_json")}
        >
          <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
            <span id="custom-json-label">Custom JSON</span>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={disabled || referenceSchemaState === "loading"}
                onClick={() => void insertReferenceSchema()}
              >
                {referenceSchemaState === "loading" ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Braces className="h-4 w-4" aria-hidden="true" />
                )}
                Insert reference schema
              </Button>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setShowCustomJsonSample((isVisible) => !isVisible)}
              >
                <Braces className="h-4 w-4" aria-hidden="true" />
                {showCustomJsonSample ? "Hide sample" : "View sample"}
              </Button>
            </div>
          </div>
          <textarea
            aria-labelledby="custom-json-label"
            className="min-h-24 w-full rounded-md border border-[#cfd8dd] bg-white px-3 py-2 font-mono text-xs"
            value={customJsonText}
            disabled={disabled}
            onChange={(event) => applyCustomJson(event.target.value)}
          />
        </div>
        {showCustomJsonSample ? (
          <div className="rounded-md border border-[#cfd8dd] bg-[#f7fafb] p-3 sm:col-span-2">
            <p className="mb-2 text-sm font-medium text-[#3a4a53]">Sample custom JSON</p>
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-white p-3 font-mono text-xs text-[#1f2933]">
              {sampleCustomJsonText}
            </pre>
          </div>
        ) : null}
      </div>
      <p className="mt-2 min-h-5 text-sm text-[#62717a]" role="status">
        {customJsonError ||
          (suggestState === "error" ? "Metadata suggestion failed." : "") ||
          (referenceSchemaState === "error" ? "Reference schema helper failed." : "")}
      </p>
    </section>
  );
}

function mergeJsonObjects(
  source: Record<string, unknown>,
  existing: Record<string, unknown>,
): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...source, ...existing };
  for (const [key, sourceValue] of Object.entries(source)) {
    const existingValue = existing[key];
    if (isPlainObject(sourceValue) && isPlainObject(existingValue)) {
      merged[key] = mergeJsonObjects(sourceValue, existingValue);
    }
  }
  return merged;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function TextField({
  label,
  value,
  disabled,
  changed,
  onChange,
}: {
  label: string;
  value: string;
  disabled: boolean;
  changed?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label
      className={
        changed
          ? "rounded-md border border-[#9ccbd8] bg-[#f3fafc] p-2 text-sm font-medium text-[#3a4a53]"
          : "text-sm font-medium text-[#3a4a53]"
      }
      {...(changed ? { "data-autosuggest-changed": "true" } : {})}
    >
      <span className="mb-1.5 block">{label}</span>
      <input
        aria-label={label}
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

const metadataFieldLabels: Record<MetadataChangeField, string> = {
  domain: "Domain",
  document_type: "Document type",
  language: "Language",
  authority: "Authority",
  source: "Source",
  collection: "Collection",
  citation_style: "Citation style",
  expected_structure: "Expected structure",
  reference_pattern: "Reference pattern",
  script: "Script",
  content_role: "Content role",
  tags: "Tags",
  metadata_sources: "Metadata sources",
  custom_json: "Custom JSON",
};

function buildMetadataChangeSet(
  before: DomainMetadata,
  after: DomainMetadata,
): MetadataChange[] {
  const changes: MetadataChange[] = [];
  const scalarFields: MetadataChangeField[] = [
    "domain",
    "document_type",
    "language",
    "authority",
    "source",
    "collection",
    "citation_style",
    "expected_structure",
    "reference_pattern",
    "script",
    "content_role",
  ];

  for (const field of scalarFields) {
    const beforeValue = getStringField(before, field);
    const afterValue = getStringField(after, field);
    if (beforeValue !== afterValue) {
      changes.push({
        field,
        label: metadataFieldLabels[field],
        summary: `${formatMetadataValue(beforeValue)} -> ${formatMetadataValue(afterValue)}`,
      });
    }
  }

  addArrayChange(changes, "tags", before.tags ?? [], after.tags ?? []);
  addArrayChange(
    changes,
    "metadata_sources",
    before.metadata_sources ?? [],
    after.metadata_sources ?? [],
  );

  const customJsonDetails = formatCustomJsonChange(
    before.custom_json ?? {},
    after.custom_json ?? {},
  );
  if (customJsonDetails.length > 0) {
    changes.push({
      field: "custom_json",
      label: metadataFieldLabels.custom_json,
      summary: `${customJsonDetails.length} custom JSON ${
        customJsonDetails.length === 1 ? "change" : "changes"
      }`,
      details: customJsonDetails,
    });
  }

  return changes;
}

function getStringField(metadata: DomainMetadata, field: MetadataChangeField): string {
  const value = metadata[field as keyof DomainMetadata];
  return typeof value === "string" ? value : "";
}

function addArrayChange(
  changes: MetadataChange[],
  field: "tags" | "metadata_sources",
  beforeValues: string[],
  afterValues: string[],
) {
  const added = afterValues.filter((item) => !beforeValues.includes(item));
  const removed = beforeValues.filter((item) => !afterValues.includes(item));
  if (added.length === 0 && removed.length === 0) {
    return;
  }

  const summary = [
    added.length > 0 ? `added ${added.join(", ")}` : null,
    removed.length > 0 ? `removed ${removed.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join("; ");

  changes.push({
    field,
    label: metadataFieldLabels[field],
    summary,
  });
}

function formatCustomJsonChange(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): string[] {
  const beforeValues = flattenCustomJson(before);
  const afterValues = flattenCustomJson(after);
  return Array.from(new Set([...Object.keys(beforeValues), ...Object.keys(afterValues)]))
    .sort()
    .flatMap((path) => {
      if (!(path in beforeValues)) {
        return [`${path} added as ${afterValues[path]}`];
      }
      if (!(path in afterValues)) {
        return [`${path} removed`];
      }
      if (beforeValues[path] !== afterValues[path]) {
        return [`${path} changed to ${afterValues[path]}`];
      }
      return [];
    });
}

function flattenCustomJson(
  value: Record<string, unknown>,
  prefix = "",
): Record<string, string> {
  return Object.entries(value).reduce<Record<string, string>>((accumulator, [key, raw]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (isPlainObject(raw)) {
      Object.assign(accumulator, flattenCustomJson(raw, path));
    } else {
      accumulator[path] = JSON.stringify(raw);
    }
    return accumulator;
  }, {});
}

function formatMetadataValue(value: string): string {
  return value.length > 0 ? value : "empty";
}
