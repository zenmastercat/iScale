"use client";
/* Sign-in with a username only. The device proves it is the device that first used the
   username by signing a server nonce with an ECDSA P-256 key that never leaves this browser
   (WebCrypto, non-extractable, kept in IndexedDB). Port of static/session.js: same DB name,
   same store, same key handling, so a browser that signed in on the old UI keeps its key. */
import { getAuthState, postChallenge, postLogin, postLogout, postRegister, postSetup } from "@/lib/api";
import { openDb, type Db } from "@/lib/idb";
import type { AuthState, User } from "@/lib/types";

let dbp: Promise<Db> | null = null;
const keysDb = () => (dbp ||= openDb("civil-scan-device", { auth: {} }));

const b64 = (buf: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(buf)));

export const normUsername = (u: string) => u.trim().toLowerCase().replace(/^@/, "");

export function state(): Promise<AuthState> {
  return getAuthState();
}

export async function signIn(rawUsername: string): Promise<User> {
  const username = normUsername(rawUsername);
  const ch = await postChallenge(username);
  const db = await keysDb();
  let pair = await db.get<CryptoKeyPair>("auth", username);
  if (!pair) {
    if (!ch.claim)
      throw new Error("This username is already linked to another device. Ask your company admin to reset it.");
    pair = (await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, [
      "sign",
      "verify",
    ])) as CryptoKeyPair;
  }
  const sig = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    pair.privateKey,
    new TextEncoder().encode(ch.message),
  );
  const spki = await crypto.subtle.exportKey("spki", pair.publicKey);
  const res = await postLogin({ username, nonce: ch.nonce, signature: b64(sig), public_key: b64(spki) });
  await db.put("auth", pair, username); // keep the key only once the server accepted it
  return res.user;
}

/* Create an account and bind this device's key in the same step, then sign in with it.
   kind: "company" (new company, you are its admin), "join" (with a join code) or "individual". */
export async function register({
  kind,
  username: rawUsername,
  displayName,
  company = "",
  joinCode = "",
}: {
  kind: "company" | "join" | "individual";
  username: string;
  displayName: string;
  company?: string;
  joinCode?: string;
}): Promise<User> {
  const username = normUsername(rawUsername);
  const pair = (await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, [
    "sign",
    "verify",
  ])) as CryptoKeyPair;
  const spki = await crypto.subtle.exportKey("spki", pair.publicKey);
  await postRegister({ kind, username, display_name: displayName, public_key: b64(spki), company, join_code: joinCode });
  await (await keysDb()).put("auth", pair, username);
  return signIn(username);
}

/* First-run: the server has no company yet. Creates it with you as admin, then signs in. */
export async function setup(company: string, username: string, displayName: string): Promise<User> {
  await postSetup({ company, username: normUsername(username), display_name: displayName });
  return signIn(username);
}

export async function signOut(): Promise<void> {
  await postLogout();
}
