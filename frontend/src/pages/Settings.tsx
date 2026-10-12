import { useCallback, useEffect, useState } from "react";
import type { Health } from "../types";
import { getHealth } from "../api";
import ErrorBanner from "../components/ErrorBanner";
import Icon from "../components/Icon";
import Card from "../components/Card";
import Spinner from "../components/Spinner";

function Dep({
  ok,
  label,
  version,
}: {
  ok: boolean;
  label: string;
  version?: string | null;
}) {
  return (
    <div className="flex items-center gap-3 p-4">
      <Icon
        name={ok ? "check_circle" : "cancel"}
        filled={ok}
        className={`text-[20px] ${ok ? "text-success" : "text-error"}`}
      />
      <span className="min-w-0 flex-1 text-body-large text-on-surface">
        {label}
      </span>
      <span className="text-body-medium text-on-surface-variant">
        {ok ? (version ?? "Disponible") : "No disponible"}
      </span>
    </div>
  );
}

function Row({
  icon,
  label,
  value,
}: {
  icon: string;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-3 p-4">
      <Icon name={icon} className="text-[20px] text-on-surface-variant" />
      <span className="min-w-0 flex-1 text-body-large text-on-surface">
        {label}
      </span>
      <span className="text-body-medium text-on-surface-variant">{value}</span>
    </div>
  );
}

export default function Settings() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setHealth(await getHealth());
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "No s’ha pogut contactar amb el servidor.",
      );
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <section className="space-y-2">
        <h2 className="px-1 text-title-medium text-on-surface">
          Entorn d’execució
        </h2>
        <Card variant="outlined" className="overflow-hidden">
          {error ? (
            <div className="p-4">
              <ErrorBanner message={error} onRetry={load} />
            </div>
          ) : !health ? (
            <div className="flex items-center gap-3 p-4 text-body-medium text-on-surface-variant">
              <Spinner /> S’estan comprovant les dependències…
            </div>
          ) : (
            <div className="divide-y divide-outline-variant">
              <Dep
                ok={health.dependencies.ffmpeg_available}
                label="FFmpeg"
                version={health.dependencies.ffmpeg_version}
              />
              <Dep
                ok={health.dependencies.node_available}
                label="Node.js"
                version={health.dependencies.node_version}
              />
              <Row
                icon="terminal"
                label="yt-dlp"
                value={health.ytdlp_version ?? "Desconegut"}
              />
              <Row
                icon="deployed_code"
                label="Aplicació"
                value={`v${health.version}`}
              />
            </div>
          )}
        </Card>
      </section>

      <section className="space-y-2">
        <h2 className="px-1 text-title-medium text-on-surface">
          Política d’emmagatzematge
        </h2>
        <Card
          variant="outlined"
          className="space-y-3 p-4 text-body-medium text-on-surface-variant"
        >
          <p>
            Quan descarregues una llista de reproducció sencera, cada vídeo es
            desa com a fitxer individual <em>i</em>, a més, s’empaqueta en un
            únic arxiu ZIP. Tant els fitxers com l’arxiu es queden a la
            biblioteca, així que pots agafar un sol vídeo o tota la llista com
            prefereixis.
          </p>
          <p>
            Eliminar un fitxer l’esborra del disc, però en conserva el registre
            a l’historial. Els fitxers eliminats d’una llista de reproducció es
            poden tornar a descarregar en qualsevol moment.
          </p>
        </Card>
      </section>

      <section className="space-y-2">
        <h2 className="px-1 text-title-medium text-on-surface">Quant a</h2>
        <Card variant="outlined" className="flex items-start gap-3 p-4">
          <Icon name="info" className="text-[20px] text-primary" />
          <p className="text-body-medium text-on-surface-variant">
            Les descàrregues es fan amb yt-dlp. Descarrega només contingut que
            tinguis autoritzat a descarregar i assegura’t de complir les lleis
            aplicables, els termes del servei de les plataformes i els drets
            del contingut.
          </p>
        </Card>
      </section>
    </div>
  );
}
