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
  const customJsonText =
    customJsonDraft ?? JSON.stringify(metadata.custom_json ?? {}, null, 2);
  const sampleCustomJsonText = JSON.stringify(sampleCustomJson, null, 2);
  const setMetadata = (patch: DomainMetadata) => {
    onChange({ ...value, domain_metadata: { ...metadata, ...patch } });
  };

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
      onChange({ ...value, domain_metadata: response.domain_metadata });
      setCustomJsonDraft(JSON.stringify(response.domain_metadata.custom_json ?? {}, null, 2));
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
          onChange={(domain) => setMetadata({ domain })}
        />
        <TextField
          label="Document type"
          value={metadata.document_type ?? ""}
          disabled={disabled}
          onChange={(document_type) => setMetadata({ document_type })}
        />
        <TextField
          label="Language"
          value={metadata.language ?? ""}
          disabled={disabled}
          onChange={(language) => setMetadata({ language })}
        />
        <TextField
          label="Collection"
          value={metadata.collection ?? ""}
          disabled={disabled}
          onChange={(collection) => setMetadata({ collection })}
        />
        <TextField
          label="Tags"
          value={(metadata.tags ?? []).join(", ")}
          disabled={disabled}
          onChange={(tags) =>
            setMetadata({ tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean) })
          }
        />
        <div className="text-sm font-medium text-[#3a4a53] sm:col-span-2">
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
  onChange,
}: {
  label: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="text-sm font-medium text-[#3a4a53]">
      <span className="mb-1.5 block">{label}</span>
      <input
        className="h-10 w-full rounded-md border border-[#cfd8dd] bg-white px-3 text-sm"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
