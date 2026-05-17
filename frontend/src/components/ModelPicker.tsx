import type { SavedModel, Role } from "../types";

const ALL_BUILTIN_MODELS = [
  { value: "gpt-5.4-mini", label: "GPT-5.4 mini", roles: ["admin", "analyst", "viewer"] },
  { value: "gpt-5.4",      label: "GPT-5.4",      roles: ["admin", "analyst"] },
];

interface Props {
  value:       string;
  savedModels: SavedModel[];
  onChange:    (modelId: string) => void;
  disabled:    boolean;
  role?:       Role;
}

export default function ModelPicker({ value, savedModels, onChange, disabled, role }: Props) {
  const builtinModels = ALL_BUILTIN_MODELS.filter(
    (m) => !role || m.roles.includes(role),
  );

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="text-sm rounded-lg px-3 py-1.5 shadow-sm cursor-pointer
                 focus:outline-none focus:ring-1 focus:ring-pink-400 focus:border-pink-400
                 disabled:opacity-50
                 bg-white dark:bg-slate-900
                 border border-gray-200 dark:border-slate-700
                 text-gray-700 dark:text-slate-300"
    >
      {builtinModels.map((m) => (
        <option key={m.value} value={m.value}>
          {m.label}
        </option>
      ))}
      {savedModels.length > 0 && (
        <optgroup label="Custom">
          {savedModels.map((m) => (
            <option key={m.id} value={m.id}>
              {m.modelName}
            </option>
          ))}
        </optgroup>
      )}
    </select>
  );
}
