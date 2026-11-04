import { Suspense } from "react";
import { LoginForm } from "./form";

export const metadata = { title: "Enter the passphrase" };

export default function LoginPage() {
  return (
    <main id="main">
      <div className="wrap" style={{ maxWidth: 480, paddingTop: 96 }}>
        <p className="wordmark" style={{ marginBottom: 32 }}>DataDraft</p>
        <Suspense>
          <LoginForm />
        </Suspense>
      </div>
    </main>
  );
}
