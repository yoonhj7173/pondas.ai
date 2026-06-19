import type { Metadata } from "next";
import { LegalShell } from "@/components/legal/LegalShell";

export const metadata: Metadata = { title: "Refund & Cancellation Policy — pondas", robots: { index: true } };

export default function Refunds() {
  return (
    <LegalShell title="Refund & Cancellation Policy" updated="June 19, 2026">
      <p>
        This policy explains cancellations and refunds for <strong>pondas</strong> (operated by Hyunjung Yoon). It
        is part of our <a href="/terms">Terms of Service</a>.
      </p>

      <h2>1. Subscriptions &amp; automatic renewal</h2>
      <p>
        Paid plans <strong>automatically renew</strong> each billing period until you cancel. You can{" "}
        <strong>cancel at any time</strong> from your account billing settings; cancellation takes effect at the end
        of the current period and stops future charges. After cancellation you keep access and any remaining
        subscription credits until that period ends. We do not provide prorated refunds for partial periods except
        where required by law.
      </p>

      <h2>2. Credit packs (one-time purchases)</h2>
      <p>
        Credit packs are digital goods delivered immediately. Because credits can be consumed right away, purchased
        credits are <strong>generally non-refundable</strong> once added to your balance, except where required by
        law. Purchased credits do not expire.
      </p>

      <h2>3. Credits for our own failures</h2>
      <p>
        If a task fails because of a problem on our side (for example, an infrastructure error, timeout, or crash),
        the credits charged for that task are <strong>refunded to your balance</strong> automatically. Credits are
        returned as credits, not as cash. If results are simply not to your satisfaction, that is not a system
        failure&mdash;you can direct the team to revise the work.
      </p>

      <h2>4. Free &amp; promotional credits</h2>
      <p>
        Free or promotional credits have no cash value, may expire, are limited per account, and are not
        refundable.
      </p>

      <h2>5. Your statutory rights</h2>
      <p>
        Nothing in this policy limits mandatory consumer rights you may have under applicable law. For example,
        consumers in the EU/EEA/UK may have a statutory right of withdrawal for certain purchases; note that for
        digital content supplied immediately with your consent, that right may not apply once delivery has begun.
        California subscribers have rights under the Automatic Renewal Law, including easy online cancellation.
      </p>

      <h2>6. How to cancel or request a refund</h2>
      <p>
        Cancel anytime from your account billing settings. For refund requests permitted under this policy or
        required by law, contact <a href="mailto:harris@vlippers.com">harris@vlippers.com</a> with your account
        email and details.
      </p>
    </LegalShell>
  );
}
