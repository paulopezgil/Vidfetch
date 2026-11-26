import Card from "../components/Card";
import Icon from "../components/Icon";
import SegmentedButton from "../components/SegmentedButton";
import { useTheme, type ThemeMode } from "../theme/ThemeProvider";

const APPEARANCE_OPTIONS = [
  { value: "system", label: "Sistema", icon: "brightness_auto" },
  { value: "light", label: "Clar", icon: "light_mode" },
  { value: "dark", label: "Fosc", icon: "dark_mode" },
];

/**
 * Appearance and language preferences.
 *
 * Appearance is fully wired to the theme provider. Language is a static
 * placeholder for now: Catalan is the only supported locale and the control is
 * disabled until the i18n layer exists.
 */
export default function Settings() {
  const { mode, resolvedTheme, setMode } = useTheme();

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8 px-4 py-6 sm:px-6 lg:px-8">
      <div>
        <h2 className="text-title-large text-on-surface">Preferències</h2>
        <p className="mt-1 text-body-medium text-on-surface-variant">
          Ajusta l’aspecte i l’idioma de la interfície.
        </p>
      </div>

      <section aria-labelledby="settings-appearance" className="space-y-3">
        <h3
          id="settings-appearance"
          className="text-title-medium text-on-surface"
        >
          Aparença
        </h3>
        <Card variant="outlined" className="space-y-4 p-4 sm:p-5">
          <div>
            <p className="text-body-large text-on-surface">Mode de color</p>
            <p className="mt-0.5 text-body-small text-on-surface-variant">
              «Sistema» segueix la configuració del dispositiu; «Clar» i «Fosc»
              la sobreescriuen.
            </p>
          </div>

          <SegmentedButton
            label="Mode de color"
            value={mode}
            onChange={(value) => setMode(value as ThemeMode)}
            options={APPEARANCE_OPTIONS}
          />

          <p
            role="status"
            aria-live="polite"
            className="flex items-center gap-2 text-body-small text-on-surface-variant"
          >
            <Icon
              name={resolvedTheme === "dark" ? "dark_mode" : "light_mode"}
              className="text-[18px]"
            />
            S’està mostrant el tema{" "}
            {resolvedTheme === "dark" ? "fosc" : "clar"}.
          </p>
        </Card>
      </section>

      <section aria-labelledby="settings-language" className="space-y-3">
        <h3
          id="settings-language"
          className="text-title-medium text-on-surface"
        >
          Idioma
        </h3>
        <Card variant="outlined" className="space-y-4 p-4 sm:p-5">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-body-large text-on-surface">
                Llengua de la interfície
              </p>
              <p className="mt-0.5 text-body-small text-on-surface-variant">
                Només hi ha un idioma disponible.
              </p>
            </div>
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-secondary-container px-3 py-1 text-label-medium text-on-secondary-container">
              <Icon name="check" className="text-[16px]" />
              Seleccionat
            </span>
          </div>

          <div
            aria-disabled="true"
            className="flex h-12 items-center justify-between gap-3 rounded-sm border border-outline-variant px-4 opacity-[0.38]"
          >
            <span className="truncate text-body-large text-on-surface">
              Català
            </span>
            <Icon name="check" className="shrink-0 text-[20px] text-on-surface" />
          </div>

          <div className="flex items-start gap-3 rounded-md bg-surface-container-high p-3 text-on-surface-variant">
            <Icon name="translate" className="shrink-0 text-[20px]" />
            <p className="text-body-small">Més idiomes aviat.</p>
          </div>
        </Card>
      </section>
    </div>
  );
}
