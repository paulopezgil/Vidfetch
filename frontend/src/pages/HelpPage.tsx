import { useState } from "react";
import Card from "../components/Card";
import Icon from "../components/Icon";
import SegmentedButton from "../components/SegmentedButton";

type Platform = "android" | "iphone" | "desktop";
type HelpSection = "install" | "download";

interface GuideStep {
  title: string;
  detail: string;
}

interface PlatformGuide {
  icon: string;
  heading: string;
  summary: string;
  steps: GuideStep[];
  note: string;
}

const SECTION_OPTIONS: { value: HelpSection; label: string; icon: string }[] = [
  { value: "install", label: "Instal·lació", icon: "add_to_home_screen" },
  { value: "download", label: "Com descarregar", icon: "download" },
];

const PLATFORM_OPTIONS: { value: Platform; label: string; icon: string }[] = [
  { value: "android", label: "Android", icon: "android" },
  { value: "iphone", label: "iPhone", icon: "phone_iphone" },
  { value: "desktop", label: "Escriptori", icon: "computer" },
];

const GUIDES: Record<Platform, PlatformGuide> = {
  android: {
    icon: "android",
    heading: "Android amb Chrome",
    summary:
      "Cal un navegador Chromium, com Chrome, Edge o Brave. El menú pot canviar una mica segons el navegador.",
    steps: [
      {
        title: "Obre Vidfetch al Chrome",
        detail: "Inicia la sessió amb el compte que vols fer servir.",
      },
      {
        title: "Toca el menú de tres punts",
        detail: "És a la cantonada superior dreta del navegador.",
      },
      {
        title:
          "Tria «Afegeix a la pantalla d’inici» o «Instal·la l’aplicació»",
        detail: "El text exacte depèn de la versió del navegador.",
      },
      {
        title: "Confirma la instal·lació",
        detail: "La icona de Vidfetch apareixerà a la pantalla d’inici.",
      },
    ],
    note:
      "Després d’instal·lar-la, l’aplicació s’obre en una finestra pròpia i les cançons desades per a ús sense connexió continuen disponibles.",
  },
  iphone: {
    icon: "phone_iphone",
    heading: "iPhone amb Safari",
    summary:
      "A l’iPhone, la instal·lació només funciona amb Safari; els altres navegadors no ofereixen aquesta opció.",
    steps: [
      {
        title: "Obre Vidfetch al Safari",
        detail: "Assegura’t que hi ets amb el compte que vols fer servir.",
      },
      {
        title: "Toca el botó Compartir",
        detail:
          "És la icona del quadrat amb una fletxa cap amunt, a la barra inferior.",
      },
      {
        title: "Tria «Afegeix a la pantalla d’inici»",
        detail: "Pot caldre desplaçar-se per la llista d’accions.",
      },
      {
        title: "Confirma amb «Afegeix»",
        detail: "La icona de Vidfetch apareixerà a la pantalla d’inici.",
      },
    ],
    note:
      "Un cop afegida, l’aplicació s’obre en mode autònom, sense la barra del navegador, i les cançons desades per a ús sense connexió continuen disponibles.",
  },
  desktop: {
    icon: "computer",
    heading: "Escriptori amb Chrome o Edge",
    summary:
      "Cal un navegador Chromium que admeti aplicacions web instal·lables, com Chrome o Edge.",
    steps: [
      {
        title: "Obre Vidfetch al Chrome o a l’Edge",
        detail: "També funciona en altres navegadors Chromium actualitzats.",
      },
      {
        title: "Fes servir la icona d’instal·lació de la barra d’adreces",
        detail:
          "Si no la veus, obre el menú del navegador i tria «Instal·la Vidfetch».",
      },
      {
        title: "Confirma la instal·lació",
        detail:
          "Es crearà una finestra pròpia i una entrada al menú d’aplicacions de l’ordinador.",
      },
    ],
    note:
      "La finestra instal·lada funciona com una aplicació independent i conserva l’accés a la biblioteca desada per a ús sense connexió.",
  },
};

const PLATFORM_TIPS = [
  "Android i escriptori: cal un navegador Chromium actualitzat (Chrome, Edge o Brave).",
  "iPhone i iPad: cal Safari; els altres navegadors no permeten instal·lar l’aplicació.",
  "Un cop instal·lada, s’obre en mode autònom, sense la barra del navegador.",
  "La biblioteca desada per a ús sense connexió continua disponible fora de línia.",
];

const DOWNLOAD_STEPS: GuideStep[] = [
  {
    title: "Obre Inici i enganxa l’enllaç",
    detail:
      "Copia l’adreça d’un vídeo o d’una llista de YouTube i enganxa-la al camp d’Inici. Prem el botó de consulta per veure què es pot descarregar.",
  },
  {
    title: "Tria la qualitat",
    detail:
      "Al menú de qualitat tria «Millor disponible», un topall «Fins a …p» (a les llistes), «Àudio (millor)» o «MP3 320». Als vídeos individuals només s’ofereixen les altures disponibles. Si el vídeo admet subtítols i els vols, activa «Incrusta els subtítols si estan disponibles» abans de descarregar.",
  },
  {
    title: "Inicia la descàrrega",
    detail:
      "El progrés de cada element es mostra a Inici. Pots seguir navegant per la resta de l’aplicació mentre la descàrrega continua.",
  },
];

const LIBRARY_RESULTS = [
  "A Biblioteca, Cançons i Vídeos mostren els fitxers descarregats.",
  "Els àlbums i els artistes agrupen automàticament les cançons descarregades, també les d’una llista de YouTube.",
  "El progrés i els errors de la descàrrega es queden a Inici; no apareixen a Biblioteca.",
];

/**
 * Ajuda: installation and download guidance.
 *
 * Vidfetch is installed from the browser rather than an app store, and every
 * platform uses a different menu, so the install steps live behind their own
 * platform switch. A separate section explains how downloads and the library
 * fit together.
 */
export default function HelpPage() {
  const [section, setSection] = useState<HelpSection>("install");
  const [platform, setPlatform] = useState<Platform>("android");
  const guide = GUIDES[platform];

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 px-4 py-6 sm:px-6 lg:px-8">
      <div>
        <h2 className="text-headline-small text-on-surface">Ajuda</h2>
        <p className="mt-2 text-body-medium text-on-surface-variant">
          Aquí trobaràs com instal·lar Vidfetch com una aplicació web i com
          descarregar música i vídeos per tenir-los a mà.
        </p>
      </div>

      <SegmentedButton
        label="Secció de l’ajuda"
        value={section}
        onChange={(value) => setSection(value as HelpSection)}
        options={SECTION_OPTIONS}
      />

      {section === "install" ? (
        <>
          <section
            aria-labelledby="install-guide-heading"
            className="space-y-4"
          >
            <div>
              <h3
                id="install-guide-heading"
                className="text-title-large text-on-surface"
              >
                Instal·la Vidfetch com a aplicació web
              </h3>
              <p className="mt-1 text-body-medium text-on-surface-variant">
                Vidfetch s’instal·la des del navegador. No cal cap botiga
                d’aplicacions: un cop instal·lada, s’obre en una finestra pròpia
                i continua funcionant sense connexió.
              </p>
            </div>

            <Card variant="outlined" className="space-y-4 p-4 sm:p-5">
              <div>
                <p className="text-title-medium text-on-surface">
                  Tria el teu dispositiu
                </p>
                <p className="mt-0.5 text-body-small text-on-surface-variant">
                  Els passos canvien segons el navegador i el sistema operatiu.
                </p>
              </div>
              <SegmentedButton
                label="Dispositiu per instal·lar Vidfetch"
                value={platform}
                onChange={(value) => setPlatform(value as Platform)}
                options={PLATFORM_OPTIONS}
              />
            </Card>
          </section>

          <section
            aria-labelledby="install-platform-heading"
            className="space-y-3"
          >
            <div className="flex items-center gap-2 px-1">
              <Icon
                name={guide.icon}
                className="text-[22px] text-on-surface-variant"
              />
              <h3
                id="install-platform-heading"
                className="text-title-medium text-on-surface"
              >
                {guide.heading}
              </h3>
            </div>

            <Card variant="outlined" className="p-4 sm:p-5">
              <p className="text-body-medium text-on-surface-variant">
                {guide.summary}
              </p>

              <ol className="mt-5 space-y-4">
                {guide.steps.map((step, index) => (
                  <li key={step.title} className="flex gap-3">
                    <span
                      aria-hidden="true"
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-container text-label-large tabular-nums text-on-primary-container"
                    >
                      {index + 1}
                    </span>
                    <div className="min-w-0">
                      <p className="text-body-large text-on-surface">
                        {step.title}
                      </p>
                      <p className="mt-0.5 text-body-small text-on-surface-variant">
                        {step.detail}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>

              <div className="mt-5 flex items-start gap-3 rounded-md bg-surface-container-high p-3">
                <Icon
                  name="info"
                  className="shrink-0 text-[20px] text-on-surface-variant"
                />
                <p className="text-body-small text-on-surface-variant">
                  {guide.note}
                </p>
              </div>
            </Card>
          </section>

          <section aria-labelledby="install-tips-heading" className="space-y-3">
            <h3
              id="install-tips-heading"
              className="px-1 text-title-medium text-on-surface"
            >
              Abans de començar
            </h3>
            <Card variant="filled" className="p-4 sm:p-5">
              <ul className="space-y-3">
                {PLATFORM_TIPS.map((tip) => (
                  <li key={tip} className="flex items-start gap-3">
                    <Icon
                      name="check_circle"
                      className="shrink-0 text-[20px] text-on-surface-variant"
                    />
                    <p className="min-w-0 text-body-medium text-on-surface-variant">
                      {tip}
                    </p>
                  </li>
                ))}
              </ul>
            </Card>
          </section>
        </>
      ) : (
        <>
          <section
            aria-labelledby="download-guide-heading"
            className="space-y-4"
          >
            <div>
              <h3
                id="download-guide-heading"
                className="text-title-large text-on-surface"
              >
                Com descarregar
              </h3>
              <p className="mt-1 text-body-medium text-on-surface-variant">
                Les descàrregues comencen sempre a Inici. Un cop acaben, els
                fitxers s’afegeixen sols a Biblioteca.
              </p>
            </div>

            <Card variant="outlined" className="p-4 sm:p-5">
              <ol className="space-y-4">
                {DOWNLOAD_STEPS.map((step, index) => (
                  <li key={step.title} className="flex gap-3">
                    <span
                      aria-hidden="true"
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-container text-label-large tabular-nums text-on-primary-container"
                    >
                      {index + 1}
                    </span>
                    <div className="min-w-0">
                      <p className="text-body-large text-on-surface">
                        {step.title}
                      </p>
                      <p className="mt-0.5 text-body-small text-on-surface-variant">
                        {step.detail}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </Card>
          </section>

          <section
            aria-labelledby="download-library-heading"
            className="space-y-3"
          >
            <h3
              id="download-library-heading"
              className="px-1 text-title-medium text-on-surface"
            >
              On apareix cada cosa
            </h3>
            <Card variant="outlined" className="p-4 sm:p-5">
              <ul className="space-y-3">
                {LIBRARY_RESULTS.map((item) => (
                  <li key={item} className="flex items-start gap-3">
                    <Icon
                      name="video_library"
                      className="shrink-0 text-[20px] text-on-surface-variant"
                    />
                    <p className="min-w-0 text-body-medium text-on-surface-variant">
                      {item}
                    </p>
                  </li>
                ))}
              </ul>
            </Card>
            <Card variant="filled" className="p-4 sm:p-5">
              <div className="flex items-start gap-3">
                <Icon
                  name="error"
                  className="shrink-0 text-[20px] text-on-surface-variant"
                />
                <p className="min-w-0 text-body-medium text-on-surface-variant">
                  Els elements que fallen o els vídeos privats no arriben mai a
                  Biblioteca. Només apareixen a la secció «Descàrregues
                  fallides» d’Inici, on pots tornar-ho a provar o cancel·lar-ho.
                </p>
              </div>
            </Card>
          </section>

          <section
            aria-labelledby="download-offline-heading"
            className="space-y-3"
          >
            <h3
              id="download-offline-heading"
              className="px-1 text-title-medium text-on-surface"
            >
              Escolta sense connexió
            </h3>
            <Card variant="outlined" className="p-4 sm:p-5">
              <ol className="space-y-4">
                <li className="flex gap-3">
                  <span
                    aria-hidden="true"
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-container text-on-primary-container"
                  >
                    <Icon name="cloud_download" className="text-[18px]" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-body-large text-on-surface">
                      Toca la icona del núvol
                    </p>
                    <p className="mt-0.5 text-body-small text-on-surface-variant">
                      A cada cançó o vídeo de Biblioteca, el control del núvol
                      desa una còpia al dispositiu.
                    </p>
                  </div>
                </li>
                <li className="flex gap-3">
                  <span
                    aria-hidden="true"
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary-container text-on-secondary-container"
                  >
                    <Icon name="check_circle" filled className="text-[18px]" />
                  </span>
                  <div className="min-w-0">
                    <p className="text-body-large text-on-surface">
                      Espera la marca de verificació
                    </p>
                    <p className="mt-0.5 text-body-small text-on-surface-variant">
                      Quan el núvol es converteix en una marca verda, el fitxer
                      ja es pot reproduir sense connexió, fins i tot en mode
                      avió.
                    </p>
                  </div>
                </li>
              </ol>
            </Card>
          </section>
        </>
      )}
    </div>
  );
}
