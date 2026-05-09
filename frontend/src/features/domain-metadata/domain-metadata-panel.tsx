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
  | "collection"
  | "tags"
  | "reference_pattern"
  | "metadata_sources"
  | "custom_json";

type MetadataChange = {
  field: MetadataChangeField;
  label: string;
  summary: string;
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
  };
  onValidityChange?: (isValid: boolean) => void;
}) {
  const metadata = value.domain_metadata ?? {};
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [customJsonDraft, setCustomJsonDraft] = useState<string | null>(null);
  const [customJsonError, setCustomJsonError] = useState("");
  const [showCustomJsonSample, setShowCustomJsonSample] = useState(false);
  const [suggestState, setSuggestState] = useState<"idle" | "loading" | "error">("idle");
  const [autosuggestChanges, setAutosuggestChanges] = useState<MetadataChange[]>([]);
  const customJsonText =
    customJsonDraft ?? JSON.stringify(metadata.custom_json ?? {}, null, 2);
  const sampleCustomJsonText = JSON.stringify(sampleCustomJson, null, 2);
  const setMetadata = (patch: DomainMetadata) => {
    onChange({ ...value, domain_metadata: { ...metadata, ...patch } });
  };
  const hasAutosuggestChange = (field: MetadataChangeField) =>
    autosuggestChanges.some((change) => change.field === field);
  const clearChangedField = (field: MetadataChangeField) => {
    setAutosuggestChanges((changes) => changes.filter((change) => change.field !== field));
  };
  const changedFieldProps = (field: MetadataChangeField) =>
    hasAutosuggestChange(field) ? { "data-autosuggest-changed": "true" } : {};

  const suggest = async () => {
    if (!suggestContext) {
      return;
    }
    setSuggestState("loading");
    try {
      const response = await apiClient.suggestDomainMetadata({
        filename: suggestContext.filename,
        content_type: suggestContext.content_type,
        profile_id: selectedProfileId || null,
        sample_text: "",
      });
      const nextMetadata = response.domain_metadata;
      setAutosuggestChanges(buildMetadataChangeSet(metadata, nextMetadata));
      onChange({ ...value, domain_metadata: nextMetadata });
      setCustomJsonDraft(JSON.stringify(nextMetadata.custom_json ?? {}, null, 2));
      setCustomJsonError("");
      onValidityChange?.(true);
      setSuggestState("idle");
    } catch {
      setSuggestState("error");
    }
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

  return (
    <section className="rounded-md border border-[#d6dde1] bg-white p-4">
      {suggestContext ? (
        <div className="mb-3 flex justify-end">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={disabled || suggestState === "loading"}
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
      {autosuggestChanges.length > 0 ? (
        <div className="mb-3 rounded-md border border-[#9ccbd8] bg-[#edf7fa] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-[#1f2933]">
              Auto-suggest updated metadata
            </p>
            <p className="text-xs font-medium text-[#176b87]">
              {autosuggestChanges.length}{" "}
              {autosuggestChanges.length === 1 ? "field changed" : "fields changed"}
            </p>
          </div>
          <dl className="mt-2 grid gap-1.5 text-xs text-[#3a4a53]">
            {autosuggestChanges.map((change) => (
              <div key={change.field} className="grid gap-1 sm:grid-cols-[150px_minmax(0,1fr)]">
                <dt className="font-semibold">{change.label}</dt>
                <dd className="min-w-0 break-words">{change.summary}</dd>
              </div>
            ))}
          </dl>
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
        <label className="text-sm font-medium text-[#3a4a53]">
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
        </label>
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
        {customJsonError || (suggestState === "error" ? "Metadata suggestion failed." : "")}
      </p>
    </section>
  );
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
  collection: "Collection",
  tags: "Tags",
  reference_pattern: "Reference pattern",
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
    "collection",
    "reference_pattern",
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

  const customJsonSummary = formatCustomJsonChange(
    before.custom_json ?? {},
    after.custom_json ?? {},
  );
  if (customJsonSummary) {
    changes.push({
      field: "custom_json",
      label: metadataFieldLabels.custom_json,
      summary: customJsonSummary,
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
): string | null {
  const beforeKeys = Object.keys(before).sort();
  const afterKeys = Object.keys(after).sort();
  const added = afterKeys.filter((key) => !beforeKeys.includes(key));
  const removed = beforeKeys.filter((key) => !afterKeys.includes(key));
  const changed = afterKeys.filter(
    (key) =>
      beforeKeys.includes(key) &&
      JSON.stringify(before[key]) !== JSON.stringify(after[key]),
  );

  if (added.length === 0 && removed.length === 0 && changed.length === 0) {
    return null;
  }

  return [
    added.length > 0 ? `added ${added.join(", ")}` : null,
    removed.length > 0 ? `removed ${removed.join(", ")}` : null,
    changed.length > 0 ? `changed ${changed.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join("; ");
}

function formatMetadataValue(value: string): string {
  return value.length > 0 ? value : "empty";
}
