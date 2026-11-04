import { useMutation, useQueryClient } from "@tanstack/react-query";
import { type SyntheticEvent, useState } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError } from "../api/client";
import { logIn, register } from "../api/session";
import styles from "./AuthForm.module.css";

const TEXT = {
  login: {
    title: "Log in",
    action: logIn,
    passwordAutocomplete: "current-password",
    other: { to: "/register", prompt: "New to Lumen?", label: "Create an account" },
  },
  register: {
    title: "Create an account",
    action: register,
    passwordAutocomplete: "new-password",
    other: { to: "/login", prompt: "Already have an account?", label: "Log in" },
  },
} as const;

function errorMessage(error: unknown): string {
  // Messages from 4xx responses are written for the user; anything else isn't.
  return error instanceof ApiError && error.status < 500 && error.code !== "unexpected_response"
    ? error.message
    : "Lumen couldn't be reached. Please try again.";
}

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const text = TEXT[mode];
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const submit = useMutation({
    mutationFn: () => text.action({ email, password }),
    onSuccess: async () => {
      queryClient.clear(); // nothing cached may carry over from a previous session
      await navigate("/");
    },
  });

  function handleSubmit(event: SyntheticEvent) {
    event.preventDefault();
    submit.mutate();
  }

  return (
    <main className={styles.card}>
      <h1>{text.title}</h1>
      <form className={styles.form} onSubmit={handleSubmit}>
        <label className={styles.field}>
          Email
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
            }}
          />
        </label>
        <label className={styles.field}>
          Password
          <input
            type="password"
            autoComplete={text.passwordAutocomplete}
            required
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
            }}
          />
        </label>
        {submit.isError && <p role="alert">{errorMessage(submit.error)}</p>}
        <button type="submit" disabled={submit.isPending}>
          {text.title}
        </button>
      </form>
      <p>
        {text.other.prompt} <Link to={text.other.to}>{text.other.label}</Link>
      </p>
    </main>
  );
}
