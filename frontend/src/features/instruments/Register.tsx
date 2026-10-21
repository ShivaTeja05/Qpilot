/**
 * Register an instrument: the name people use for it (required), and optionally a short id, its
 * make and model, where it stands and whether it is shared (a core facility). Serial numbers are
 * never typed: they are linked from the instrument's own run files.
 */
import { Plus } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Button, Dialog, Field, Input, Switch } from "@/ui";
import { useRegister } from "./api";

const ID_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;

export function RegisterButton({
  variant = "primary",
  label = "Register an instrument",
}: {
  variant?: "primary" | "secondary";
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const formId = useId();
  const [name, setName] = useState("");
  const [id, setId] = useState("");
  const [model, setModel] = useState("");
  const [location, setLocation] = useState("");
  const [shared, setShared] = useState(false);
  const [tried, setTried] = useState(false);
  const reset = () => {
    setName("");
    setId("");
    setModel("");
    setLocation("");
    setShared(false);
    setTried(false);
  };
  const register = useRegister(() => {
    setOpen(false);
    reset();
  });

  const nameError =
    tried && !name.trim() ? "Give the instrument the name people use for it." : null;
  const idError =
    id.trim() && !ID_RE.test(id.trim())
      ? "Lower-case letters, digits, - or _ (at most 64), starting with a letter or a digit."
      : null;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setTried(true);
    if (!name.trim() || idError) return;
    register.mutate({
      display_name: name.trim(),
      instrument_id: id.trim() || null,
      make_model: model.trim(),
      location: location.trim(),
      shared,
    });
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) reset();
      }}
      trigger={
        <Button variant={variant} icon={<Plus />}>
          {label}
        </Button>
      }
      title="Register an instrument"
      description="Its serial numbers are never typed here: they are linked, on this computer only, when you say which instrument a run file is from."
      footer={
        <>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button type="submit" form={formId} variant="primary" loading={register.isPending}>
            Register
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <Field label="Name" hint="The name people in the lab use for it." error={nameError}>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            required
            autoComplete="off"
          />
        </Field>
        <Field label="Short id" optional hint="Made from the name when left empty." error={idError}>
          <Input
            value={id}
            onChange={(e) => setId(e.target.value)}
            maxLength={64}
            className="font-mono"
            autoComplete="off"
          />
        </Field>
        <Field label="Make and model" optional>
          <Input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            maxLength={200}
            autoComplete="off"
          />
        </Field>
        <Field label="Where it stands" optional>
          <Input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            maxLength={200}
            autoComplete="off"
          />
        </Field>
        <Switch
          checked={shared}
          onCheckedChange={setShared}
          label="Shared instrument"
          hint="Used by several groups, such as a core facility's."
        />
      </form>
    </Dialog>
  );
}
