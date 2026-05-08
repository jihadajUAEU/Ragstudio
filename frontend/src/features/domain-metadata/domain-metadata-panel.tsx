import type {
  DomainMetadata,
  DomainProfileOut,
  IndexDocumentIn,
  ParserMode,
} from "../../api/generated";

const parserOptions: Array<{ value: ParserMode; label: string }> = [
  { value: "local_fallback", label: "Local fallback" },
  { value: "mineru_strict", label: "MinerU strict" },
  { value: "mineru_with_fallback", label: "MinerU with fallback" },
];

export function DomainMetadataPanel({
  profiles,
  value,
  onChange,
  disabled = false,
}: {
  profiles: DomainProfileOut[];
  value: IndexDocumentIn;
  onChange: (value: IndexDocumentIn) => void;
  disabled?: boolean;
}) {
  const metadata = value.domain_metadata ?? {};
  const setMetadata = (patch: DomainMetadata) => {
    onChange({ ...value, domain_metadata: { ...metadata, ...patch } });
  };

  return (
    <section className="rounded-md border border-[#d6dde1] bg-white p-4">
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
            onChange={(event) => {
              const profile = profiles.find((item) => item.id === event.target.value);
              if (profile) {
                onChange({ ...value, domain_metadata: profile.metadata });
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
      </div>
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
