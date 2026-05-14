const MODELS = [
  { value: "gpt-5.4-mini", label: "GPT-5.4 mini" },
  { value: "gpt-5.4",      label: "GPT-5.4" },
];

interface Props {
  value: string;
  onChange: (model: string) => void;
  disabled: boolean;
}

export default function ModelPicker({ value, onChange, disabled }: Props) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="bg-slate-800 border border-slate-600 text-slate-300 text-sm rounded-md px-3 py-1.5
                 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 cursor-pointer"
    >
      {MODELS.map((m) => (
        <option key={m.value} value={m.value}>
          {m.label}
        </option>
      ))}
    </select>
  );
}
