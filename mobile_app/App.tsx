import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Location from "expo-location";
import * as Notifications from "expo-notifications";
import { StatusBar } from "expo-status-bar";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

const STORAGE_KEY = "station-server-url";
const POLL_INTERVAL_MS = 3000;
const REQUEST_TIMEOUT_MS = 8000;

type Weather = {
  ok?: boolean;
  temp?: number;
  rh?: number;
  cloud?: number;
  ghi?: number;
  wind?: number;
  phrase?: string;
  from_phone?: boolean;
  error?: string;
};

type Zone = {
  name: string;
  humidity: number;
  soil: number;
  valve: boolean;
  flow: number;
  flow_expected: number;
  flow_ratio: number;
  pressure: number;
  irrigation_minutes: number;
  moisture_gain: number;
  diagnosis: string;
  diagnosis_level: "bad" | "warn" | "";
  demo_fault: "normal" | "blocked" | "no_response";
  status: "red" | "yellow" | "green";
  need: number;
};

type FieldPoint = {
  zone: Zone;
  x: number;
  y: number;
};

type StationAlert = {
  id: number;
  text: string;
  level: "bad" | "warn" | "info";
  time: string;
};

type StationState = {
  clock: string;
  mode: string;
  paused: boolean;
  tank_pct: number;
  tank_l: number;
  pressure: number;
  well: number;
  pv_power: number;
  pv_temp: number;
  cooling: boolean;
  brine: number;
  drip: number;
  pump_on: boolean;
  desal_eff: number;
  desal_state: string;
  zones: Zone[];
  alarms: { text: string; level: "bad" | "warn" }[];
  notifications: StationAlert[];
  weather: Weather;
};

const COLORS = {
  background: "#F3F6FA",
  card: "#FFFFFF",
  border: "#D5DEE8",
  text: "#1C2430",
  muted: "#5C6B7A",
  blue: "#1A73E8",
  green: "#1F9D55",
  yellow: "#C8880B",
  red: "#D64545",
  track: "#E6EDF4",
};

const statusColor = (level: string) =>
  level === "bad" || level === "red"
    ? COLORS.red
    : level === "warn" || level === "yellow"
      ? COLORS.yellow
      : COLORS.green;

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

function formatNumber(value: number | undefined, digits = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "—";
}

function normalizeServerUrl(value: string) {
  let parsed: URL;
  try {
    parsed = new URL(value.trim());
  } catch {
    throw new Error("Saisissez l'adresse complète, par ex. http://192.168.1.20:8765");
  }
  if (
    (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
    !parsed.hostname ||
    (parsed.pathname !== "/" && parsed.pathname !== "") ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error("Saisissez l'adresse de la station, par ex. http://192.168.1.20:8765");
  }
  return parsed.origin;
}

function Card({ children }: { children: ReactNode }) {
  return <View style={styles.card}>{children}</View>;
}

function Metric({
  title,
  value,
  detail,
}: {
  title: string;
  value: string;
  detail: string;
}) {
  return (
    <View style={styles.metric}>
      <Text style={styles.muted}>{title}</Text>
      <Text style={styles.metricValue}>{value}</Text>
      <Text style={styles.muted}>{detail}</Text>
    </View>
  );
}

function FieldOverview({
  zones,
  selectedZone,
  onSelectZone,
  onSetDemoFault,
  pendingFault,
}: {
  zones: Zone[];
  selectedZone: string | null;
  onSelectZone: (zone: string | null) => void;
  onSetDemoFault: (zone: string, fault: Zone["demo_fault"]) => void;
  pendingFault: string | null;
}) {
  const points: FieldPoint[] = zones.map((zone, index) => ({
    zone,
    x: [17, 39, 62, 84][index] ?? 17 + (index % 4) * 22,
    y: [37, 66, 41, 69][index] ?? (index % 2 === 0 ? 37 : 66),
  }));
  const average =
    zones.length > 0
      ? zones.reduce((total, zone) => total + zone.humidity, 0) / zones.length
      : 0;
  const dryCount = zones.filter((zone) => zone.humidity < 30).length;
  const anomalyCount = zones.filter((zone) => Boolean(zone.diagnosis)).length;
  const selected = points.find((point) => point.zone.name === selectedZone)?.zone;

  return (
    <Card>
      <View style={styles.rowBetween}>
        <View>
          <Text style={styles.sectionTitle}>Vue de la parcelle</Text>
          <Text style={styles.muted}>Touchez un secteur pour le diagnostiquer</Text>
        </View>
        <View style={styles.compass}>
          <Text style={styles.compassText}>N</Text>
          <Text style={styles.compassArrow}>↑</Text>
        </View>
      </View>

      <View style={styles.fieldMap}>
        <View style={styles.fieldSoil} />
        {Array.from({ length: 9 }, (_, index) => (
          <View
            key={`row-${index}`}
            style={[styles.fieldRow, { top: `${8 + index * 11}%` }]}
          />
        ))}
        {[25, 50, 75].map((x) => (
          <View key={`column-${x}`} style={[styles.fieldColumn, { left: `${x}%` }]} />
        ))}

        <View style={styles.mapTag}>
          <Text style={styles.mapTagText}>ZONES · HUMIDITÉ & IRRIGATION</Text>
        </View>
        <View style={styles.mapNorth}>
          <Text style={styles.mapNorthText}>N</Text>
          <Text style={styles.mapNorthArrow}>↑</Text>
        </View>

        {points.map(({ zone, x, y }) => {
          const color = zone.diagnosis
            ? statusColor(zone.diagnosis_level || "bad")
            : statusColor(zone.status);
          const isSelected = selectedZone === zone.name;
          return (
            <View
              key={zone.name}
              style={[styles.sensorPosition, { left: `${x}%`, top: `${y}%` }]}
            >
              <View
                pointerEvents="none"
                style={[styles.heatHaloOuter, { backgroundColor: color }]}
              />
              <View
                pointerEvents="none"
                style={[styles.heatHaloInner, { backgroundColor: color }]}
              />
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Secteur ${zone.name}, humidité ${Math.round(zone.humidity)} pour cent`}
                accessibilityState={{ selected: isSelected }}
                onPress={() => onSelectZone(isSelected ? null : zone.name)}
                style={({ pressed }) => [
                  styles.sensorNode,
                  { backgroundColor: color },
                  isSelected && styles.sensorNodeSelected,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.sensorLabel}>{zone.name}</Text>
              </Pressable>
            </View>
          );
        })}
        <View pointerEvents="none" style={styles.mapScale}>
          <View style={styles.mapScaleLine} />
          <Text style={styles.mapScaleText}>Parcelle · vue schématique</Text>
        </View>
      </View>

      <View style={styles.mapStats}>
        <View style={styles.mapStat}>
          <Text style={styles.muted}>Humidité moyenne</Text>
          <Text style={styles.mapStatValue}>{formatNumber(average)} %</Text>
        </View>
        <View style={styles.mapStat}>
          <Text style={styles.muted}>Anomalies</Text>
          <Text style={[styles.mapStatValue, { color: anomalyCount ? COLORS.red : COLORS.green }]}>
            {anomalyCount} / {zones.length}
          </Text>
        </View>
        <View style={styles.mapStat}>
          <Text style={styles.muted}>Secteurs secs</Text>
          <Text style={[styles.mapStatValue, { color: dryCount ? COLORS.red : COLORS.green }]}>
            {dryCount} / {zones.length}
          </Text>
        </View>
      </View>

      <View style={styles.mapLegend}>
        {[
          ["red", "Anomalie / sec"],
          ["yellow", "Pression basse"],
          ["green", "Débit normal"],
        ].map(([level, label]) => (
          <View key={level} style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: statusColor(level) }]} />
            <Text style={styles.legendText}>{label}</Text>
          </View>
        ))}
      </View>

      {selected ? (
        <View
          style={[
            styles.selectedZone,
            {
              borderLeftColor: selected.diagnosis
                ? statusColor(selected.diagnosis_level || "bad")
                : statusColor(selected.status),
            },
          ]}
        >
          <Text style={styles.zoneTitle}>Secteur {selected.name}</Text>
          <Text style={styles.muted}>
            Humidité {formatNumber(selected.humidity)} % · ligne{" "}
            {selected.valve ? "ouverte" : "fermée"}
            {"\n"}Débit {formatNumber(selected.flow, 1)} /{" "}
            {formatNumber(selected.flow_expected, 1)} L/min · pression{" "}
            {formatNumber(selected.pressure, 2)} bar
            {"\n"}Réponse du sol {formatNumber(selected.moisture_gain, 1)} % après{" "}
            {formatNumber(selected.irrigation_minutes, 1)} min
          </Text>
          {selected.diagnosis ? (
            <Text
              style={[
                styles.diagnosisText,
                { color: statusColor(selected.diagnosis_level || "bad") },
              ]}
            >
              {selected.diagnosis}
            </Text>
          ) : null}
          <Text style={styles.smallNote}>
            Essai de simulation uniquement — aucun matériel n'est commandé.
          </Text>
          <Pressable
            disabled={pendingFault !== null}
            onPress={() => onSetDemoFault(selected.name, "blocked")}
            style={({ pressed }) => [
              styles.secondaryButton,
              pressed && styles.pressed,
              pendingFault !== null && styles.disabled,
            ]}
          >
            <Text style={styles.secondaryButtonText}>
              {pendingFault === `${selected.name}:blocked`
                ? "Simulation en cours…"
                : "Tester un goutteur bouché"}
            </Text>
          </Pressable>
          <Pressable
            disabled={pendingFault !== null}
            onPress={() => onSetDemoFault(selected.name, "no_response")}
            style={({ pressed }) => [
              styles.secondaryButton,
              pressed && styles.pressed,
              pendingFault !== null && styles.disabled,
            ]}
          >
            <Text style={styles.secondaryButtonText}>
              {pendingFault === `${selected.name}:no_response`
                ? "Simulation en cours…"
                : "Tester sans hausse d'humidité"}
            </Text>
          </Pressable>
          {selected.demo_fault !== "normal" ? (
            <Pressable
              disabled={pendingFault !== null}
              onPress={() => onSetDemoFault(selected.name, "normal")}
              style={({ pressed }) => [
                styles.restoreButton,
                pressed && styles.pressed,
                pendingFault !== null && styles.disabled,
              ]}
            >
              <Text style={styles.restoreButtonText}>Rétablir le secteur</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      <Text style={styles.mapDisclaimer}>
        Carte et capteurs de démonstration. Les sondes capacitives ESP32 ne sont pas
        encore connectées.
      </Text>
    </Card>
  );
}

export default function App() {
  const [draftUrl, setDraftUrl] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [station, setStation] = useState<StationState | null>(null);
  const [connectionError, setConnectionError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [sendingLocation, setSendingLocation] = useState(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState(false);
  const [selectedFieldZone, setSelectedFieldZone] = useState<string | null>(null);
  const [pendingFault, setPendingFault] = useState<string | null>(null);
  const [pendingCommand, setPendingCommand] = useState<string | null>(null);
  const inFlight = useRef(false);
  const primedAlerts = useRef(false);
  const lastAlertId = useRef(0);
  const previousServerUrl = useRef("");

  useEffect(() => {
    let active = true;
    AsyncStorage.getItem(STORAGE_KEY)
      .then((savedUrl) => {
        if (active && savedUrl) {
          setDraftUrl(savedUrl);
          setServerUrl(savedUrl);
        }
      })
      .catch(() => {
        if (active) setNotice("Impossible de charger l'adresse enregistrée.");
      });

    Notifications.getPermissionsAsync()
      .then(({ status }) => {
        if (active) setNotificationsEnabled(status === "granted");
      })
      .catch(() => {
        if (active) setNotice("État des notifications indisponible.");
      });

    if (Platform.OS === "android") {
      Notifications.setNotificationChannelAsync("station-alerts", {
        name: "Alertes de la station",
        importance: Notifications.AndroidImportance.DEFAULT,
        vibrationPattern: [0, 180],
        lightColor: COLORS.blue,
      }).catch(() => {
        if (active) setNotice("Impossible de configurer le canal de notifications.");
      });
    }

    return () => {
      active = false;
    };
  }, []);

  const pollStation = useCallback(async () => {
    if (!serverUrl || inFlight.current) return;
    inFlight.current = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(`${serverUrl}/api/state`, {
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`Le serveur a répondu avec le code ${response.status}.`);
      }
      const nextState = (await response.json()) as StationState;
      if (typeof nextState.tank_pct !== "number" || !Array.isArray(nextState.zones)) {
        throw new Error("Réponse invalide. Vérifiez que l'adresse correspond à la station.");
      }
      setStation(nextState);
      setConnectionError("");

      const alerts = Array.isArray(nextState.notifications)
        ? nextState.notifications
        : [];
      if (!primedAlerts.current) {
        lastAlertId.current = alerts.reduce(
          (highest, alert) => Math.max(highest, alert.id),
          0,
        );
        primedAlerts.current = true;
      } else {
        const freshAlerts = alerts.filter(
          (alert) => alert.id > lastAlertId.current,
        );
        for (const alert of freshAlerts) {
          if (notificationsEnabled) {
            await Notifications.scheduleNotificationAsync({
              content: {
                title: "Station d'irrigation",
                body: alert.text,
                data: { level: alert.level },
              },
              trigger: null,
            }).catch(() => {
              setNotice("Alerte reçue dans l'application, notification système indisponible.");
            });
          }
        }
        if (alerts.length > 0) {
          lastAlertId.current = alerts.reduce(
            (highest, alert) => Math.max(highest, alert.id),
            lastAlertId.current,
          );
        }
      }
    } catch (error) {
      setConnectionError(
        error instanceof Error
          ? error.name === "AbortError"
            ? "Délai dépassé. Vérifiez le Wi-Fi et l'adresse de la station."
            : error.message
          : "Impossible de joindre la station.",
      );
    } finally {
      clearTimeout(timeout);
      inFlight.current = false;
      setLoading(false);
      setRefreshing(false);
    }
  }, [notificationsEnabled, serverUrl]);

  useEffect(() => {
    if (!serverUrl) return;
    if (previousServerUrl.current !== serverUrl) {
      previousServerUrl.current = serverUrl;
      primedAlerts.current = false;
      lastAlertId.current = 0;
    }
    setLoading(true);
    void pollStation();
    const interval = setInterval(() => void pollStation(), POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [pollStation, serverUrl]);

  const connect = async () => {
    try {
      const normalized = normalizeServerUrl(draftUrl);
      setDraftUrl(normalized);
      setStation(null);
      setConnectionError("");
      setServerUrl(normalized);
      setNotice("");
      try {
        await AsyncStorage.setItem(STORAGE_KEY, normalized);
      } catch {
        setNotice("Connecté, mais l'adresse n'a pas pu être mémorisée.");
      }
    } catch (error) {
      setConnectionError(
        error instanceof Error ? error.message : "Adresse de station invalide.",
      );
    }
  };

  const refresh = () => {
    if (!serverUrl) return;
    setRefreshing(true);
    void pollStation();
  };

  const enableNotifications = async () => {
    try {
      const current = await Notifications.getPermissionsAsync();
      const permission =
        current.status === "granted"
          ? current
          : await Notifications.requestPermissionsAsync();
      const enabled = permission.status === "granted";
      setNotificationsEnabled(enabled);
      setNotice(
        enabled
          ? "Les alertes de la station pourront apparaître comme notifications."
          : "Permission refusée. Les alertes restent visibles dans l'application.",
      );
    } catch {
      setNotice("Impossible d'activer les notifications. Les alertes restent visibles dans l'application.");
    }
  };

  const sendPhoneLocation = async () => {
    if (!serverUrl) return;
    setSendingLocation(true);
    setNotice("");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS * 2);
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (permission.status !== "granted") {
        throw new Error("Autorisez la position pour demander la météo locale.");
      }
      const position = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      const response = await fetch(`${serverUrl}/api/location`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
        }),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`La station a refusé la position (${response.status}).`);
      }
      setNotice("Position envoyée. La météo locale va être actualisée.");
      await pollStation();
    } catch (error) {
      setNotice(
        error instanceof Error && error.name === "AbortError"
          ? "La station ne répond pas. Vérifiez le Wi-Fi et réessayez."
          : error instanceof Error
            ? error.message
            : "Impossible d'envoyer la position.",
      );
    } finally {
      clearTimeout(timeout);
      setSendingLocation(false);
    }
  };

  const setDemoFault = async (
    zone: string,
    fault: Zone["demo_fault"],
  ) => {
    if (!serverUrl || pendingFault) return;
    const requestId = `${zone}:${fault}`;
    setPendingFault(requestId);
    setNotice("");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(`${serverUrl}/api/demo/fault`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ zone, fault }),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(
          response.status === 404
            ? "Mettez à jour le programme de la station pour activer les tests."
            : `La station a refusé le test (${response.status}).`,
        );
      }
      setNotice(
        fault === "normal"
          ? `Simulation réparée pour le secteur ${zone}.`
          : `Test de détection lancé sur le secteur ${zone}.`,
      );
      await pollStation();
    } catch (error) {
      setNotice(
        error instanceof Error && error.name === "AbortError"
          ? "Délai dépassé. Vérifiez la liaison avec la station."
          : error instanceof Error
            ? error.message
            : "Impossible de lancer le test de détection.",
      );
    } finally {
      clearTimeout(timeout);
      setPendingFault(null);
    }
  };

  const sendControlCommand = async (
    command:
      | { type: "zone"; zone: string; open: boolean }
      | { type: "mode"; mode: "AUTO" | "MANUEL" },
  ) => {
    if (!serverUrl || pendingCommand) return;
    const requestId =
      command.type === "zone"
        ? `${command.zone}:${command.open ? "open" : "close"}`
        : `mode:${command.mode}`;
    setPendingCommand(requestId);
    setNotice("");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const isZoneCommand = command.type === "zone";
      const response = await fetch(
        `${serverUrl}/api/control/${isZoneCommand ? "zone" : "mode"}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            isZoneCommand
              ? { zone: command.zone, open: command.open }
              : { mode: command.mode },
          ),
          signal: controller.signal,
        },
      );
      if (!response.ok) {
        throw new Error(
          response.status === 404
            ? "Mettez à jour le programme de la station pour activer les commandes."
            : response.status === 503
              ? "La station est occupée. Attendez quelques secondes puis réessayez."
              : `La station a refusé la commande (${response.status}).`,
        );
      }
      setNotice(
        command.type === "zone"
          ? `Commande ${command.open ? "d'ouverture" : "de fermeture"} envoyée pour la zone ${command.zone}.`
          : `Passage au mode ${command.mode} demandé.`,
      );
    } catch (error) {
      setNotice(
        error instanceof Error && error.name === "AbortError"
          ? "Délai dépassé. Vérifiez la liaison avec la station."
          : error instanceof Error
            ? error.message
            : "Impossible d'envoyer la commande.",
      );
    } finally {
      clearTimeout(timeout);
      setPendingCommand(null);
    }
  };

  return (
    <View style={styles.screen}>
      <StatusBar style="dark" />
      <ScrollView
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={refresh}
            tintColor={COLORS.blue}
          />
        }
      >
        <View style={styles.header}>
          <Text style={styles.title}>Station d'irrigation</Text>
          <Text style={styles.subtitle}>
            Solaire · osmose inverse · eau · agriculture
          </Text>
        </View>

        <Card>
          <Text style={styles.sectionTitle}>Connexion à la station</Text>
          <Text style={styles.muted}>
            Entrez l'adresse affichée dans le programme sur l'ordinateur.
          </Text>
          <TextInput
            value={draftUrl}
            onChangeText={setDraftUrl}
            placeholder="http://192.168.1.20:8765"
            placeholderTextColor="#8B98A8"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            returnKeyType="go"
            onSubmitEditing={connect}
            style={styles.input}
          />
          <Pressable
            onPress={connect}
            style={({ pressed }) => [styles.primaryButton, pressed && styles.pressed]}
          >
            <Text style={styles.primaryButtonText}>
              {serverUrl ? "Connecter / actualiser" : "Connecter"}
            </Text>
          </Pressable>
          <View style={styles.connectionRow}>
            {loading ? (
              <ActivityIndicator size="small" color={COLORS.blue} />
            ) : (
              <View
                style={[
                  styles.statusDot,
                  {
                    backgroundColor: connectionError
                      ? COLORS.red
                      : station
                        ? COLORS.green
                        : COLORS.yellow,
                  },
                ]}
              />
            )}
            <Text style={styles.connectionText}>
              {connectionError
                ? "Liaison perdue"
                : station
                ? `Connecté · ${station.clock} · ${station.mode}`
                : serverUrl
                  ? "Connexion en cours…"
                  : "En attente de l'adresse"}
            </Text>
          </View>
          {connectionError ? (
            <Text style={styles.errorText}>{connectionError}</Text>
          ) : null}
        </Card>

        {station ? (
          <>
            <FieldOverview
              zones={station.zones}
              selectedZone={selectedFieldZone}
              onSelectZone={setSelectedFieldZone}
              onSetDemoFault={setDemoFault}
              pendingFault={pendingFault}
            />

            <Card>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionTitle}>Météo du site</Text>
                <Text style={styles.muted}>
                  {station.weather?.from_phone ? "Position du téléphone" : "Site configuré"}
                </Text>
              </View>
              <Text style={styles.weatherValue}>
                {station.weather?.ok
                  ? `${formatNumber(station.weather.temp, 1)} °C · ${station.weather.phrase ?? ""}`
                  : "Météo indisponible"}
              </Text>
              <Text style={styles.muted}>
                Nuages {formatNumber(station.weather?.cloud)} % · vent{" "}
                {formatNumber(station.weather?.wind)} km/h · soleil{" "}
                {formatNumber(station.weather?.ghi)} W/m²
              </Text>
              <Pressable
                onPress={sendPhoneLocation}
                disabled={sendingLocation}
                style={({ pressed }) => [
                  styles.secondaryButton,
                  pressed && styles.pressed,
                  sendingLocation && styles.disabled,
                ]}
              >
                <Text style={styles.secondaryButtonText}>
                  {sendingLocation ? "Envoi de la position…" : "Utiliser la position du téléphone"}
                </Text>
              </Pressable>
            </Card>

            <View style={styles.metricGrid}>
              <Metric
                title="Réservoir"
                value={`${formatNumber(station.tank_pct)} %`}
                detail={`${formatNumber(station.tank_l)} L`}
              />
              <Metric
                title="Solaire"
                value={`${formatNumber(station.pv_power)} W`}
                detail={`${formatNumber(station.pv_temp, 1)} °C panneaux`}
              />
              <Metric
                title="Goutte-à-goutte"
                value={`${formatNumber(station.drip, 1)} L/min`}
                detail={station.pump_on ? "Pompe en marche" : "Pompe arrêtée"}
              />
              <Metric
                title="Osmose / pression"
                value={`${formatNumber(station.desal_eff)} %`}
                detail={`${formatNumber(station.pressure, 2)} bar`}
              />
            </View>

            <Card>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionTitle}>Zones d'irrigation</Text>
                <Text style={styles.muted}>Mode {station.mode}</Text>
              </View>
              <Text style={styles.smallNote}>
                Commandes de démonstration uniquement. Commander une vanne passe la station en mode manuel.
              </Text>
              {station.mode !== "AUTO" ? (
                <Pressable
                  accessibilityRole="button"
                  disabled={pendingCommand !== null}
                  onPress={() =>
                    void sendControlCommand({ type: "mode", mode: "AUTO" })
                  }
                  style={({ pressed }) => [
                    styles.primaryButton,
                    pressed && styles.pressed,
                    pendingCommand !== null && styles.disabled,
                  ]}
                >
                  <Text style={styles.primaryButtonText}>
                    {pendingCommand === "mode:AUTO"
                      ? "Envoi de la commande…"
                      : "Revenir au mode automatique"}
                  </Text>
                </Pressable>
              ) : null}
              {station.zones.map((zone) => (
                <View key={zone.name} style={styles.zone}>
                  <View style={styles.rowBetween}>
                    <Text style={styles.zoneTitle}>Zone {zone.name}</Text>
                    <Text style={[styles.zoneValue, { color: statusColor(zone.status) }]}>
                      {formatNumber(zone.humidity)} %
                    </Text>
                  </View>
                  <View style={styles.progressTrack}>
                    <View
                      style={[
                        styles.progressFill,
                        {
                          width: `${Math.max(0, Math.min(100, zone.humidity))}%`,
                          backgroundColor: statusColor(zone.status),
                        },
                      ]}
                    />
                  </View>
                  <Text style={styles.muted}>
                    Ligne {zone.valve ? "ouverte" : "fermée"} · sol{" "}
                    {formatNumber(zone.soil, 1)} °C · besoin {formatNumber(zone.need)} %
                    {"\n"}Débit {formatNumber(zone.flow, 1)} /{" "}
                    {formatNumber(zone.flow_expected, 1)} L/min · pression{" "}
                    {formatNumber(zone.pressure, 2)} bar
                  </Text>
                  {zone.diagnosis ? (
                    <Text
                      style={[
                        styles.diagnosisText,
                        { color: statusColor(zone.diagnosis_level || "bad") },
                      ]}
                    >
                      {zone.diagnosis}
                    </Text>
                  ) : null}
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel={`${zone.valve ? "Fermer" : "Ouvrir"} la ligne d'irrigation de la zone ${zone.name}`}
                    disabled={pendingCommand !== null}
                    onPress={() =>
                      void sendControlCommand({
                        type: "zone",
                        zone: zone.name,
                        open: !zone.valve,
                      })
                    }
                    style={({ pressed }) => [
                      zone.valve ? styles.restoreButton : styles.primaryButton,
                      pressed && styles.pressed,
                      pendingCommand !== null && styles.disabled,
                    ]}
                  >
                    <Text
                      style={
                        zone.valve
                          ? styles.restoreButtonText
                          : styles.primaryButtonText
                      }
                    >
                      {pendingCommand ===
                      `${zone.name}:${zone.valve ? "close" : "open"}`
                        ? "Envoi de la commande…"
                        : zone.valve
                          ? "Fermer la ligne"
                          : "Ouvrir la ligne"}
                    </Text>
                  </Pressable>
                </View>
              ))}
            </Card>

            <Card>
              <View style={styles.rowBetween}>
                <Text style={styles.sectionTitle}>Alertes</Text>
                <Text style={styles.muted}>
                  {station.paused ? "Simulation en pause" : `Mise à jour toutes les ${POLL_INTERVAL_MS / 1000} s`}
                </Text>
              </View>
              {station.notifications.length === 0 ? (
                <Text style={styles.muted}>Aucune alerte enregistrée.</Text>
              ) : (
                station.notifications.slice().reverse().slice(0, 8).map((alert) => (
                  <View
                    key={alert.id}
                    style={[
                      styles.alert,
                      { borderLeftColor: statusColor(alert.level) },
                    ]}
                  >
                    <Text style={styles.alertText}>{alert.text}</Text>
                    <Text style={styles.muted}>{alert.time}</Text>
                  </View>
                ))
              )}
              <Pressable
                onPress={enableNotifications}
                style={({ pressed }) => [
                  styles.secondaryButton,
                  pressed && styles.pressed,
                ]}
              >
                <Text style={styles.secondaryButtonText}>
                  {notificationsEnabled
                    ? "Notifications système activées"
                    : "Activer les notifications"}
                </Text>
              </Pressable>
              <Text style={styles.smallNote}>
                Gardez l'application ouverte pour les mesures et alertes en direct.
              </Text>
            </Card>
          </>
        ) : (
          <Card>
            <Text style={styles.sectionTitle}>Prêt à se connecter</Text>
            <Text style={styles.muted}>
              Lancez la station sur l'ordinateur, puis saisissez son adresse réseau
              ci-dessus. Les deux appareils doivent être sur le même Wi-Fi.
            </Text>
          </Card>
        )}

        {notice ? <Text style={styles.notice}>{notice}</Text> : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: COLORS.background },
  content: { padding: 16, paddingBottom: 36, gap: 12 },
  header: { paddingVertical: 8 },
  title: { color: COLORS.text, fontSize: 26, fontWeight: "800" },
  subtitle: { color: COLORS.muted, fontSize: 14, marginTop: 4 },
  card: {
    backgroundColor: COLORS.card,
    borderColor: COLORS.border,
    borderWidth: 1,
    borderRadius: 16,
    padding: 16,
    gap: 10,
  },
  sectionTitle: { color: COLORS.text, fontSize: 17, fontWeight: "700" },
  muted: { color: COLORS.muted, fontSize: 13, lineHeight: 19 },
  input: {
    backgroundColor: "#F6F8FB",
    borderColor: COLORS.border,
    borderWidth: 1,
    borderRadius: 10,
    color: COLORS.text,
    fontSize: 15,
    paddingHorizontal: 12,
    paddingVertical: 11,
    marginTop: 2,
  },
  primaryButton: {
    backgroundColor: COLORS.blue,
    borderRadius: 10,
    padding: 13,
    alignItems: "center",
  },
  primaryButtonText: { color: "#FFFFFF", fontSize: 15, fontWeight: "700" },
  secondaryButton: {
    backgroundColor: "#E7EEF8",
    borderRadius: 10,
    padding: 11,
    alignItems: "center",
    marginTop: 4,
  },
  secondaryButtonText: { color: COLORS.text, fontSize: 14, fontWeight: "600" },
  restoreButton: {
    backgroundColor: "#FDECEC",
    borderRadius: 10,
    padding: 11,
    alignItems: "center",
    marginTop: 4,
  },
  restoreButtonText: { color: COLORS.red, fontSize: 14, fontWeight: "700" },
  pressed: { opacity: 0.78 },
  disabled: { opacity: 0.55 },
  connectionRow: { flexDirection: "row", alignItems: "center", gap: 8, minHeight: 22 },
  statusDot: { width: 9, height: 9, borderRadius: 6 },
  connectionText: { color: COLORS.text, fontSize: 13 },
  errorText: { color: COLORS.red, fontSize: 13, lineHeight: 19 },
  weatherValue: { color: COLORS.text, fontSize: 22, fontWeight: "700" },
  rowBetween: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
  },
  metricGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  metric: {
    flexGrow: 1,
    flexBasis: "47%",
    backgroundColor: COLORS.card,
    borderColor: COLORS.border,
    borderWidth: 1,
    borderRadius: 14,
    padding: 14,
    gap: 4,
  },
  metricValue: { color: COLORS.text, fontSize: 22, fontWeight: "800" },
  zone: { borderTopColor: COLORS.track, borderTopWidth: 1, paddingTop: 11, gap: 6 },
  zoneTitle: { color: COLORS.text, fontWeight: "600", fontSize: 15 },
  zoneValue: { fontWeight: "800", fontSize: 16 },
  progressTrack: {
    height: 8,
    borderRadius: 8,
    backgroundColor: COLORS.track,
    overflow: "hidden",
  },
  progressFill: { height: "100%", borderRadius: 8 },
  alert: {
    backgroundColor: "#F6F8FB",
    borderLeftWidth: 4,
    borderRadius: 8,
    padding: 10,
    gap: 3,
  },
  alertText: { color: COLORS.text, fontSize: 14, fontWeight: "600" },
  smallNote: { color: COLORS.muted, fontSize: 12, lineHeight: 17 },
  notice: { color: COLORS.muted, fontSize: 13, paddingHorizontal: 4 },
  compass: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: COLORS.border,
    alignItems: "center",
    justifyContent: "center",
  },
  compassText: { color: COLORS.muted, fontSize: 9, fontWeight: "800" },
  compassArrow: { color: COLORS.red, fontSize: 14, lineHeight: 15, fontWeight: "800" },
  fieldMap: {
    height: 270,
    borderRadius: 12,
    overflow: "hidden",
    position: "relative",
    backgroundColor: "#547247",
  },
  fieldSoil: {
    ...StyleSheet.absoluteFill,
    backgroundColor: "#62794A",
    opacity: 0.72,
  },
  fieldRow: {
    position: "absolute",
    left: "-12%",
    width: "124%",
    height: 2,
    backgroundColor: "rgba(228, 223, 190, 0.44)",
    transform: [{ rotate: "-16deg" }],
  },
  fieldColumn: {
    position: "absolute",
    top: "-15%",
    height: "130%",
    width: 1,
    backgroundColor: "rgba(255, 255, 255, 0.24)",
  },
  mapTag: {
    position: "absolute",
    top: 10,
    left: 10,
    backgroundColor: "rgba(20, 35, 29, 0.76)",
    borderRadius: 6,
    paddingHorizontal: 9,
    paddingVertical: 6,
  },
  mapTagText: { color: "#FFFFFF", fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },
  mapNorth: {
    position: "absolute",
    top: 9,
    right: 10,
    width: 32,
    height: 38,
    borderRadius: 16,
    backgroundColor: "rgba(20, 35, 29, 0.76)",
    alignItems: "center",
    justifyContent: "center",
  },
  mapNorthText: { color: "#FFFFFF", fontSize: 9, fontWeight: "800" },
  mapNorthArrow: { color: "#F06B56", fontSize: 15, lineHeight: 16, fontWeight: "800" },
  sensorPosition: {
    position: "absolute",
    width: 52,
    height: 52,
    alignItems: "center",
    justifyContent: "center",
    marginLeft: -26,
    marginTop: -26,
  },
  heatHaloOuter: {
    position: "absolute",
    width: 50,
    height: 50,
    borderRadius: 25,
    opacity: 0.22,
  },
  heatHaloInner: {
    position: "absolute",
    width: 34,
    height: 34,
    borderRadius: 17,
    opacity: 0.34,
  },
  sensorNode: {
    width: 29,
    height: 29,
    borderRadius: 16,
    borderColor: "#FFFFFF",
    borderWidth: 2,
    alignItems: "center",
    justifyContent: "center",
    elevation: 3,
    shadowColor: "#111827",
    shadowOpacity: 0.28,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 2 },
  },
  sensorNodeSelected: { borderWidth: 3, borderColor: "#173BFF" },
  sensorLabel: { color: "#FFFFFF", fontSize: 11, fontWeight: "900" },
  mapScale: {
    position: "absolute",
    left: 10,
    bottom: 10,
    backgroundColor: "rgba(20, 35, 29, 0.76)",
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 6,
    gap: 4,
  },
  mapScaleLine: {
    width: 45,
    height: 3,
    borderTopColor: "#FFFFFF",
    borderTopWidth: 1,
    borderBottomColor: "#FFFFFF",
    borderBottomWidth: 1,
  },
  mapScaleText: { color: "#FFFFFF", fontSize: 10 },
  mapStats: { flexDirection: "row", justifyContent: "space-between", gap: 8 },
  mapStat: { flex: 1, gap: 3 },
  mapStatValue: { color: COLORS.text, fontSize: 16, fontWeight: "800" },
  mapLegend: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 5 },
  legendDot: { width: 9, height: 9, borderRadius: 5 },
  legendText: { color: COLORS.muted, fontSize: 11 },
  selectedZone: {
    borderLeftWidth: 4,
    borderRadius: 6,
    backgroundColor: "#F6F8FB",
    padding: 10,
    gap: 4,
  },
  diagnosisText: { fontSize: 13, lineHeight: 18, fontWeight: "700" },
  mapDisclaimer: { color: COLORS.muted, fontSize: 11, lineHeight: 16 },
});
