import { useState } from "react";
import Card from "../components/Card";
import Icon from "../components/Icon";
import SegmentedButton from "../components/SegmentedButton";

type Platform = "android" | "iphone" | "desktop";

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
        title:
          "Fes servir la icona d’instal·lació de la barra d’adreces",
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

/**
 * PWA installation guide.
 *
 * Vidfetch is installed from the browser rather than an app store, and every
 * platform uses a different menu, so the steps live behind a segmented switch.
 * The page always exposes the switch and defaults to Android.
 */
export default function InstallGuide() {
  const [platform, setPlatform] = useState<Platform>("android");
  const guide = GUIDES[platform];

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 px-4 py-6 sm:px-6 lg:px-8">
      <div>
        <h2 className="text-headline-small text-on-surface">
          Instal·la Vidfetch
        </h2>
        <p className="mt-2 text-body-medium text-on-surface-variant">
          Vidfetch s’instal·la com una aplicació web des del navegador. No cal
          cap botiga d’aplicacions: un cop instal·lada, s’obre en una finestra
          pròpia i continua funcionant sense connexió.
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

      <section aria-labelledby="install-platform-heading" className="space-y-3">
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
    </div>
  );
}
