import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { errorMessage } from "../api/client";
import { fetchContext, type PersonalContext, saveContext } from "../api/context";
import styles from "./ContextScreen.module.css";

const MAX_LENGTH = 750;

/** Spec 010: a short description of the person's own normal, used to read their notes. */
export function ContextScreen() {
  const context = useQuery({ queryKey: ["context"], queryFn: fetchContext });

  return (
    <section>
      <h1>Personal context</h1>
      <p>
        Describe what's normal for you, so suggestions read your notes the way you mean them. For
        example: "Waking a few times at night is normal for me, and I fall asleep again quickly."
      </p>
      <p className={styles.note}>
        It stays on this computer and only the local model sees it. It helps the model read your
        note, but it can't create a score or a tag on its own.
      </p>
      {context.isPending && <p>Loading…</p>}
      {context.isError && <p role="alert">{errorMessage(context.error)}</p>}
      {context.isSuccess && <ContextForm saved={context.data} />}
    </section>
  );
}

function ContextForm({ saved }: { saved: PersonalContext }) {
  const [text, setText] = useState(saved.text);
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: () => saveContext(text),
    onSuccess: (stored) => {
      queryClient.setQueryData(["context"], stored);
      setText(stored.text);
    },
  });

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
    >
      <label htmlFor="personal-context">Your personal context</label>
      <textarea
        id="personal-context"
        rows={6}
        maxLength={MAX_LENGTH}
        autoComplete="off"
        spellCheck={false}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          save.reset();
        }}
      />
      <p className={styles.note}>
        {text.length} / {MAX_LENGTH}
      </p>
      <div className={styles.actions}>
        <button type="submit" disabled={save.isPending}>
          Save
        </button>
        {save.isSuccess && <span role="status">Saved</span>}
        {save.isError && <span role="alert">{errorMessage(save.error)}</span>}
      </div>
    </form>
  );
}
