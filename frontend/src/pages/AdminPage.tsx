import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../auth/AuthProvider";
import type { AdminUser, AdminUserList } from "../types/auth";
import { approveUser, listAdminUsers, revokeUser } from "../lib/api";
import { formatDate } from "../lib";
import AdminPasswordResetDialog from "../components/AdminPasswordResetDialog";
import Button from "../components/Button";
import Card from "../components/Card";
import EmptyState from "../components/EmptyState";
import ErrorBanner from "../components/ErrorBanner";
import Icon from "../components/Icon";
import Spinner from "../components/Spinner";
import { useToast } from "../components/Toast";

function ApprovalChip({ approved }: { approved: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-label-medium ${
        approved
          ? "bg-success-container text-on-success-container"
          : "bg-warning-container text-on-warning-container"
      }`}
    >
      <Icon
        name={approved ? "check_circle" : "schedule"}
        className="text-[16px]"
      />
      {approved ? "Aprovat" : "Pendent"}
    </span>
  );
}

function RoleChip({ role }: { role: AdminUser["app_role"] }) {
  const isAdmin = role === "admin";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-label-medium ${
        isAdmin
          ? "bg-primary-container text-on-primary-container"
          : "bg-surface-container-highest text-on-surface-variant"
      }`}
    >
      <Icon
        name={isAdmin ? "shield_person" : "person"}
        className="text-[16px]"
      />
      {isAdmin ? "Administrador" : "Usuari"}
    </span>
  );
}

export default function AdminPage() {
  const { profile: me } = useAuth();
  const toast = useToast();
  const [data, setData] = useState<AdminUserList | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [resetUser, setResetUser] = useState<AdminUser | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await listAdminUsers({ limit: 100 });
      setData(next);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "No s’ha pogut carregar la llista.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  }

  async function mutate(user: AdminUser, action: "approve" | "revoke") {
    setBusyId(user.id);
    try {
      if (action === "approve") {
        await approveUser(user.id);
      } else {
        await revokeUser(user.id);
      }
      toast(
        action === "approve"
          ? `Accés aprovat per a ${user.email}`
          : `Accés revocat per a ${user.email}`,
        "success",
      );
      await load();
    } catch (e) {
      const message =
        e instanceof Error ? e.message : "No s’ha pogut actualitzar l’usuari.";
      setError(message);
      toast(message, "error");
    } finally {
      setBusyId(null);
    }
  }

  const users = data?.users ?? [];
  const pendingCount = users.filter((user) => !user.is_approved).length;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-title-large text-on-surface">Usuaris</h2>
          <p className="mt-1 text-body-medium text-on-surface-variant">
            Aprova o revoca l’accés dels comptes. Els canvis són immediats al
            servidor.
          </p>
        </div>
        <Button
          variant="tonal"
          onClick={() => void handleRefresh()}
          disabled={refreshing || busyId !== null}
        >
          {refreshing ? (
            <Spinner />
          ) : (
            <Icon name="refresh" className="text-[20px]" />
          )}
          Actualitza
        </Button>
      </div>

      {error ? <ErrorBanner message={error} onRetry={() => void load()} /> : null}

      {loading ? (
        <div
          className="flex items-center justify-center gap-3 py-16 text-body-medium text-on-surface-variant"
          role="status"
          aria-live="polite"
        >
          <Spinner /> Carregant usuaris…
        </div>
      ) : users.length === 0 ? (
        <EmptyState
          icon="group"
          title="Encara no hi ha usuaris"
          description="Quan algú creï un compte, apareixerà aquí per aprovar-lo."
        />
      ) : (
        <>
          <p className="text-body-small text-on-surface-variant">
            {data?.total ?? users.length} usuaris · {pendingCount} pendents
            d’aprovació
          </p>
          <Card variant="outlined" className="overflow-hidden">
            {users.map((user, index) => {
              const isSelf = user.id === me?.id;
              const busy = busyId === user.id;
              return (
                <div
                  key={user.id}
                  className={`flex flex-col gap-3 p-4 sm:flex-row sm:items-center ${
                    index > 0 ? "border-t border-outline-variant" : ""
                  }`}
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary-container text-title-medium text-on-primary-container">
                    {(user.email || "?").charAt(0).toUpperCase()}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate text-title-small text-on-surface">
                        {user.email || "(sense correu)"}
                      </p>
                      {isSelf ? (
                        <span className="rounded-sm bg-secondary-container px-2 py-0.5 text-label-small text-on-secondary-container">
                          Tu
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <ApprovalChip approved={user.is_approved} />
                      <RoleChip role={user.app_role} />
                      {user.approved_at ? (
                        <span className="text-body-small text-on-surface-variant">
                          Aprovat el {formatDate(user.approved_at)}
                        </span>
                      ) : user.created_at ? (
                        <span className="text-body-small text-on-surface-variant">
                          Creat el {formatDate(user.created_at)}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <Button
                      variant="outlined"
                      size="sm"
                      onClick={() => setResetUser(user)}
                      disabled={isSelf || busyId !== null}
                      title={
                        isSelf
                          ? "Utilitza Configuració per canviar la teva contrasenya"
                          : undefined
                      }
                    >
                      <Icon name="key" className="text-[18px]" />
                      Restableix la contrasenya
                    </Button>
                    {user.is_approved ? (
                      <Button
                        variant="outlined"
                        size="sm"
                        onClick={() => void mutate(user, "revoke")}
                        disabled={isSelf || busyId !== null}
                        title={
                          isSelf
                            ? "No pots revocar el teu propi compte"
                            : undefined
                        }
                      >
                        {busy ? (
                          <Spinner />
                        ) : (
                          <Icon name="block" className="text-[18px]" />
                        )}
                        Revoca
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() => void mutate(user, "approve")}
                        disabled={busyId !== null}
                      >
                        {busy ? (
                          <Spinner />
                        ) : (
                          <Icon name="check" className="text-[18px]" />
                        )}
                        Aprova
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </Card>
        </>
      )}

      <AdminPasswordResetDialog
        open={resetUser !== null}
        user={resetUser}
        onClose={() => setResetUser(null)}
        onReset={(user) =>
          toast(`Contrasenya restablerta per a ${user.email}`, "success")
        }
      />
    </div>
  );
}
