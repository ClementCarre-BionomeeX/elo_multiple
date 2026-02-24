from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Ensure repository root is importable when running `streamlit run` without installation.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

import altair as alt
import pandas as pd
import streamlit as st

from elo_app.application.services import RatingService, RulesRegistry
from elo_app.domain.models import Outcome, Team
from elo_app.infrastructure.db import create_connection, init_db
from elo_app.infrastructure.repos import SQLiteRepository
from elo_app.rules.belote import BeloteRules
from elo_app.rules.tarot import TarotRules


def _get_service() -> tuple[RatingService, Any]:
    needs_refresh = "rating_service" not in st.session_state or not all(
        hasattr(st.session_state["rating_service"], attr)
        for attr in (
            "get_open_match",
            "get_trueskill_progression",
            "get_surprise_series",
            "get_current_trueskill_stats",
            "get_current_player_stats",
        )
    )
    if needs_refresh:
        conn = create_connection("elo_app.db")
        init_db(conn)
        repo = SQLiteRepository(conn)
        registry = RulesRegistry()
        registry.register("belote", BeloteRules())
        registry.register("tarot", TarotRules())
        st.session_state["rating_service"] = RatingService(repo, registry)
        st.session_state["db_conn"] = conn
    return st.session_state["rating_service"], st.session_state["db_conn"]


def _fetch_rows(conn, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = conn.execute(query, params)
    return [dict(row) for row in cur.fetchall()]


def _select_box(
    label: str, rows: list[dict[str, Any]], key_field: str = "id", key: str | None = None
) -> str | None:
    if not rows:
        st.info(f"Aucun élément pour {label}")
        return None
    labels = {
        row[key_field]: f'{row.get("name", row[key_field])} ({row[key_field][:8]})' for row in rows
    }
    ids = [row[key_field] for row in rows]
    # For small choices, radio buttons feel snappier; fall back to selectbox otherwise.
    if len(ids) <= 5:
        return st.radio(label, ids, format_func=lambda _id: labels[_id], key=key, horizontal=True)
    return st.selectbox(label, ids, format_func=lambda _id: labels[_id], key=key)


def parse_ts_list(raw_ts_list: list[Any]) -> pd.Series:
    parsed = []
    bad_values = []
    for ts in raw_ts_list:
        dt = None
        if ts is None or (isinstance(ts, float) and pd.isna(ts)):
            dt = pd.NaT
        elif isinstance(ts, (int, float)):
            val = float(ts)
            if val < 1e11:
                dt = pd.to_datetime(val, unit="s", utc=True, errors="coerce")
            elif val < 1e14:
                dt = pd.to_datetime(val, unit="ms", utc=True, errors="coerce")
            else:
                dt = pd.to_datetime(val, unit="ns", utc=True, errors="coerce")
        else:
            dt = pd.to_datetime(ts, utc=True, errors="coerce")

        if pd.isna(dt):
            bad_values.append(ts)
        else:
            parsed.append(dt)

    if bad_values:
        st.warning(f"Horodatages invalides ignorés: {bad_values}")
    if not parsed:
        return pd.Series(dtype="datetime64[ns]")
    series = pd.Series(parsed, dtype="datetime64[ns, UTC]")
    series = series.dt.tz_convert("Europe/Paris").dt.tz_localize(None)
    return series


def page_home():
    st.set_page_config(page_title="Elo multi-jeux", layout="wide")
    st.title("Elo multi-jeux")
    st.caption("Saisissez rapidement vos rounds, puis gérez et administrez les sessions.")

    service, conn = _get_service()
    players = _fetch_rows(conn, "SELECT id, name FROM players ORDER BY name")
    player_lookup = {p["id"]: p["name"] for p in players}
    groups = _fetch_rows(conn, "SELECT id, name FROM groups ORDER BY name")
    games = _fetch_rows(conn, "SELECT id, name, ruleset_id FROM games ORDER BY name")

    tab_manage, tab_rounds, tab_dashboard, tab_admin = st.tabs(
        ["Gestion", "Rounds", "Dashboard", "Admin"]
    )

    with tab_manage:
        st.subheader("Créer des entités")
        with st.expander("Nouveau joueur"):
            name = st.text_input("Nom du joueur", key="player_name")
            if st.button("Créer joueur"):
                if name:
                    player_id = service.create_player(name)
                    st.success(f"Joueur créé: {name} ({player_id})")
                else:
                    st.error("Renseignez un nom.")

        with st.expander("Nouveau groupe"):
            group_name = st.text_input("Nom du groupe")
            member_ids = st.multiselect(
                "Membres",
                [p["id"] for p in players],
                format_func=lambda pid: player_lookup.get(pid, pid),
            )
            if st.button("Créer groupe"):
                if group_name and member_ids:
                    group_id = service.create_group(group_name, member_ids)
                    st.success(f"Groupe créé ({group_id})")
                else:
                    st.error("Nom et membres requis.")

        with st.expander("Nouveau jeu"):
            game_name = st.text_input("Nom du jeu")
            ruleset = st.selectbox("Ruleset", ["belote", "tarot"])
            k_value = st.number_input("K (optionnel)", value=20, step=1)
            if st.button("Créer jeu"):
                if game_name:
                    game_id = service.create_game(
                        game_name, ruleset_id=ruleset, config={"K": k_value}
                    )
                    st.success(f"Jeu créé ({game_id})")
                else:
                    st.error("Nom requis.")

    with tab_rounds:
        st.subheader("Saisir des rounds")
        selected_group = _select_box("Groupe", groups, key="rounds_group")
        selected_game = _select_box("Jeu", games, key="rounds_game")

        if selected_group and selected_game:
            open_match = service.get_open_match(selected_group, selected_game)
            matches = _fetch_rows(
                conn,
                "SELECT * FROM matches WHERE group_id=? AND game_id=? ORDER BY started_at DESC",
                (selected_group, selected_game),
            )
            matches_open = [m for m in matches if m["ended_at"] is None]
            if open_match:
                st.caption(f"Session ouverte: {open_match.id[:8]} démarrée {open_match.started_at}")
            else:
                st.caption("Aucune session ouverte.")
            with st.expander("Créer une session"):
                participant_ids = st.multiselect(
                    "Participants",
                    [p["id"] for p in players],
                    format_func=lambda pid: player_lookup.get(pid, pid),
                )
                if open_match:
                    st.info("Une session est déjà ouverte. Fermez-la pour en créer une nouvelle.")
                    if st.button("Terminer la session ouverte"):
                        service.end_match(open_match.id)
                        st.success("Session clôturée.")
                        st.rerun()
                else:
                    if st.button("Créer session"):
                        if participant_ids:
                            match_id = service.create_match(
                                selected_group, selected_game, participant_ids
                            )
                            st.success(f"Session créée ({match_id})")
                            st.rerun()
                        else:
                            st.error("Choisissez au moins un participant.")

            st.subheader("Ajouter un round")
            match_id = _select_box("Session", matches_open, key_field="id", key="rounds_match")
            if match_id:
                match_row = next(m for m in matches_open if m["id"] == match_id)
                participant_ids = json.loads(match_row["participant_ids_json"])
                game_row = next(g for g in games if g["id"] == selected_game)
                ruleset_id = game_row["ruleset_id"]
                participant_labels = {
                    pid: next((p["name"] for p in players if p["id"] == pid), pid)
                    for pid in participant_ids
                }

                if ruleset_id == "belote":
                    st.markdown("**Belote — saisie rapide**")
                    team_a = st.multiselect(
                        "Équipe A",
                        participant_ids,
                        max_selections=2,
                        key=f"belote_team_a_{match_id}",
                        format_func=lambda pid: participant_labels[pid],
                    )
                    remaining = [pid for pid in participant_ids if pid not in team_a]
                    team_b = st.multiselect(
                        "Équipe B",
                        remaining,
                        max_selections=2,
                        key=f"belote_team_b_{match_id}",
                        format_func=lambda pid: participant_labels[pid],
                    )
                    margin = st.number_input(
                        "Marge (optionnel)", value=0, step=10, key=f"belote_margin_{match_id}"
                    )
                    if len(team_a) == 2 and len(team_b) == 2:
                        col_a, col_b, col_d = st.columns(3)

                        def _add_belote_round(winner: str) -> None:
                            outcome = Outcome(
                                type="winloss",
                                data={"winner": winner, "margin": margin if margin else None},
                            )
                            event = service.add_round(
                                match_id,
                                teams=[Team("A", team_a), Team("B", team_b)],
                                outcome=outcome,
                            )
                            st.success(f"Round ajouté. Deltas: {event.deltas}")

                        if col_a.button("Victoire équipe A", key=f"a_win_{match_id}"):
                            _add_belote_round("A")
                        if col_b.button("Victoire équipe B", key=f"b_win_{match_id}"):
                            _add_belote_round("B")
                        if col_d.button("Match nul", key=f"draw_{match_id}"):
                            _add_belote_round("draw")
                    else:
                        st.info(
                            "Sélectionnez 2 joueurs dans chaque équipe pour activer les boutons."
                        )
                elif ruleset_id == "tarot":
                    attack = st.multiselect(
                        "Camp ATT (preneur + partenaire éventuel)",
                        participant_ids,
                        max_selections=2,
                        key=f"tarot_attack_{match_id}",
                        format_func=lambda pid: participant_labels[pid],
                    )
                    defense = [pid for pid in participant_ids if pid not in attack]
                    success = st.checkbox(
                        "Contrat réussi ?", value=True, key=f"tarot_success_{match_id}"
                    )
                    margin = st.number_input(
                        "Marge (optionnel)", value=0, step=10, key=f"tarot_margin_{match_id}"
                    )
                    if st.button("Enregistrer round tarot", key=f"tarot_submit_{match_id}"):
                        if attack and defense:
                            outcome = Outcome(
                                type="contract",
                                data={"success": success, "margin": margin if margin else None},
                            )
                            event = service.add_round(
                                match_id,
                                teams=[Team("ATT", attack), Team("DEF", defense)],
                                outcome=outcome,
                            )
                            st.success(f"Round ajouté. Deltas: {event.deltas}")
                        else:
                            st.error("Sélectionnez au moins un ATT et un DEF.")

        st.subheader("Classement")
        stats = service.get_current_player_stats(selected_group, selected_game)
        if stats:
            player_lookup = {
                row["id"]: row["name"] for row in _fetch_rows(conn, "SELECT id, name FROM players")
            }
            df_rows = []
            for row in stats:
                df_rows.append(
                    {
                        "Joueur": player_lookup.get(row["player_id"], row["player_id"]),
                        "Elo": int(round(row["elo"])),
                        "Skill (est.)": f"{row['ts_mu']:.1f}",
                        "Skill (confiant)": f"{row['ts_cons']:.1f}",
                        "Incertitude": f"{row['ts_sigma']:.1f}",
                    }
                )
            st.dataframe(df_rows, width="stretch")
        else:
            st.info("Aucun rating encore enregistré.")

    with tab_dashboard:
        st.subheader("Dashboard")
        selected_group_dash = _select_box("Groupe", groups, key="dash_group")
        selected_game_dash = _select_box("Jeu", games, key="dash_game")
        if selected_group_dash and selected_game_dash:
            stats_dash = service.get_current_player_stats(selected_group_dash, selected_game_dash)
            player_lookup = {
                row["id"]: row["name"] for row in _fetch_rows(conn, "SELECT id, name FROM players")
            }
            st.markdown("**Classement actuel**")
            if stats_dash:
                df_rows = []
                for row in stats_dash:
                    df_rows.append(
                        {
                            "Joueur": player_lookup.get(row["player_id"], row["player_id"]),
                            "Elo": int(round(row["elo"])),
                            "Skill (est.)": round(row["ts_mu"], 1),
                            "Skill (confiant)": round(row["ts_cons"], 1),
                            "Incertitude": round(row["ts_sigma"], 1),
                        }
                    )
                st.dataframe(df_rows, width="stretch")
            else:
                st.info("Aucun rating encore enregistré.")

            st.markdown("**Progression d'un joueur**")
            group_members = _fetch_rows(
                conn,
                """
                SELECT p.id, p.name
                FROM players p
                JOIN group_members gm ON gm.player_id = p.id
                WHERE gm.group_id = ?
                ORDER BY p.name
                """,
                (selected_group_dash,),
            )
            player_id = _select_box(
                "Joueur",
                group_members,
                key_field="id",
                key="dash_player",
            )
            if player_id:
                elo_history = service.get_player_round_history(
                    selected_group_dash, selected_game_dash, player_id
                )
                ts_series_all = service.get_trueskill_progression(
                    selected_group_dash, selected_game_dash
                )
                surprise_series_all = service.get_surprise_series(
                    selected_group_dash, selected_game_dash
                )
                ts_series = ts_series_all.get(player_id, [])
                surprise_series = surprise_series_all.get(player_id, [])

                elo_tab, ts_tab, perf_tab = st.tabs(
                    ["Elo", "TrueSkill (μ/σ)", "Perf vs attente"]
                )

                with elo_tab:
                    if elo_history:
                        ordered = sorted(elo_history, key=lambda t: t[0])
                        ratings_only = [val for _, val, _ in ordered]
                        times = parse_ts_list([ts for ts, _, _ in ordered])
                        if times.empty:
                            st.warning(
                                "Impossible d'afficher l'historique : horodatages invalides."
                            )
                        else:
                            ymin = min(ratings_only) - 40
                            ymax = max(ratings_only) + 40
                            times = pd.to_datetime(times, errors="raise").dt.tz_localize(None)
                            idx_vals = list(range(len(times)))
                            chart_df = pd.DataFrame(
                                {
                                    "idx": idx_vals,
                                    "time": times,
                                    "rating": ratings_only,
                                    "match_id": [m for _, _, m in ordered],
                                }
                            )
                            boundaries = []
                            for i in range(1, len(chart_df)):
                                if chart_df["match_id"].iloc[i] != chart_df["match_id"].iloc[i - 1]:
                                    boundaries.append(
                                        {
                                            "idx": chart_df["idx"].iloc[i],
                                            "match_id": chart_df["match_id"].iloc[i],
                                            "time": chart_df["time"].iloc[i],
                                        }
                                    )

                            base_chart = (
                                alt.Chart(chart_df)
                                .mark_line(point=True, interpolate="monotone")
                                .encode(
                                    x=alt.X(
                                        "idx:Q",
                                        title="Round",
                                        axis=alt.Axis(tickMinStep=1, tickCount=10),
                                    ),
                                    y=alt.Y(
                                        "rating:Q",
                                        title="Rating",
                                        scale=alt.Scale(domain=[ymin, ymax]),
                                    ),
                                    order=alt.Order("idx:Q"),
                                    tooltip=[
                                        alt.Tooltip("time:T", title="Date"),
                                        "rating:Q",
                                        alt.Tooltip("match_id:N", title="Session"),
                                    ],
                                )
                            )
                            rules = (
                                alt.Chart(pd.DataFrame(boundaries))
                                .mark_rule(strokeDash=[2, 2], opacity=0.3)
                                .encode(
                                    x="idx:Q",
                                    tooltip=[
                                        alt.Tooltip("match_id:N", title="Session"),
                                        alt.Tooltip("time:T", title="Début session"),
                                    ],
                                )
                            )
                            st.altair_chart(
                                (base_chart + rules).properties(height=280),
                                width="stretch",
                            )
                    else:
                        st.info("Pas encore de rounds pour ce joueur dans ce jeu.")

                with ts_tab:
                    if ts_series:
                        ts_df = pd.DataFrame(ts_series)
                        show_conservative = st.checkbox(
                            "Afficher μ-3σ", value=True, key="show_conservative"
                        )
                        show_sigma = st.checkbox(
                            "Afficher σ (ligne)", value=False, key="show_sigma"
                        )
                        base = (
                            alt.Chart(ts_df)
                            .mark_line(point=True, interpolate="monotone")
                            .encode(
                                x=alt.X(
                                    "idx:Q",
                                    title="Round",
                                    axis=alt.Axis(tickMinStep=1, tickCount=10),
                                ),
                                y="mu:Q",
                                tooltip=[
                                    alt.Tooltip("time:T", title="Date"),
                                    alt.Tooltip("mu:Q", title="μ"),
                                    alt.Tooltip("sigma:Q", title="σ"),
                                    alt.Tooltip("conservative:Q", title="μ-3σ"),
                                    alt.Tooltip("match_id:N", title="Session"),
                                ],
                            )
                        )
                        layers = [base]
                        if show_conservative:
                            layers.append(
                                alt.Chart(ts_df)
                                .mark_line(strokeDash=[4, 2], opacity=0.6)
                                .encode(x="idx:Q", y="conservative:Q")
                            )
                        if show_sigma:
                            layers.append(
                                alt.Chart(ts_df)
                                .mark_line(strokeDash=[1, 3], opacity=0.6, color="orange")
                                .encode(x="idx:Q", y="sigma:Q")
                            )
                        boundaries_ts = []
                        for i in range(1, len(ts_df)):
                            if ts_df["match_id"].iloc[i] != ts_df["match_id"].iloc[i - 1]:
                                boundaries_ts.append(
                                    {
                                        "idx": ts_df["idx"].iloc[i],
                                        "match_id": ts_df["match_id"].iloc[i],
                                        "time": ts_df["time"].iloc[i],
                                    }
                                )
                        if boundaries_ts:
                            layers.append(
                                alt.Chart(pd.DataFrame(boundaries_ts))
                                .mark_rule(strokeDash=[2, 2], opacity=0.3)
                                .encode(
                                    x="idx:Q",
                                    tooltip=[
                                        alt.Tooltip("match_id:N", title="Session"),
                                        alt.Tooltip("time:T", title="Début session"),
                                    ],
                                )
                            )
                        st.altair_chart(alt.layer(*layers).properties(height=280), width="stretch")
                    else:
                        st.info("Pas encore de rounds pour calculer TrueSkill.")

                with perf_tab:
                    if surprise_series:
                        perf_df = pd.DataFrame(surprise_series)
                        base = (
                            alt.Chart(perf_df)
                            .mark_line(point=True, interpolate="monotone")
                            .encode(
                                x=alt.X(
                                    "idx:Q",
                                    title="Round",
                                    axis=alt.Axis(tickMinStep=1, tickCount=10),
                                ),
                                y=alt.Y("cum_p:Q", title="Surprise cumulée (S-E)"),
                                tooltip=[
                                    alt.Tooltip("time:T", title="Date"),
                                    alt.Tooltip("expected:Q", title="E"),
                                    alt.Tooltip("actual:Q", title="S"),
                                    alt.Tooltip("p:Q", title="S-E"),
                                    alt.Tooltip("cum_p:Q", title="Cum."),
                                    alt.Tooltip("match_id:N", title="Session"),
                                ],
                            )
                        )
                        boundaries_perf = []
                        for i in range(1, len(perf_df)):
                            if perf_df["match_id"].iloc[i] != perf_df["match_id"].iloc[i - 1]:
                                boundaries_perf.append(
                                    {
                                        "idx": perf_df["idx"].iloc[i],
                                        "match_id": perf_df["match_id"].iloc[i],
                                        "time": perf_df["time"].iloc[i],
                                    }
                                )
                        layers = [base]
                        if boundaries_perf:
                            layers.append(
                                alt.Chart(pd.DataFrame(boundaries_perf))
                                .mark_rule(strokeDash=[2, 2], opacity=0.3)
                                .encode(
                                    x="idx:Q",
                                    tooltip=[
                                        alt.Tooltip("match_id:N", title="Session"),
                                        alt.Tooltip("time:T", title="Début session"),
                                    ],
                                )
                            )
                        st.altair_chart(
                            alt.layer(*layers).properties(height=280), width="stretch"
                        )
                    else:
                        st.info("Pas encore de rounds pour calculer la perf vs attente.")
    with tab_admin:
        st.subheader("Admin — rounds & recalcul")
        selected_group_admin = _select_box("Groupe", groups, key_field="id", key="admin_group")
        selected_game_admin = _select_box("Jeu", games, key_field="id", key="admin_game")

        if selected_group_admin and selected_game_admin:
            if st.button("Recalculer tous les ratings"):
                service.recalc_game(selected_group_admin, selected_game_admin)
                st.success("Recalcul terminé.")

            matches_admin = _fetch_rows(
                conn,
                "SELECT * FROM matches WHERE group_id=? AND game_id=? ORDER BY started_at DESC",
                (selected_group_admin, selected_game_admin),
            )
            match_admin_id = _select_box("Session", matches_admin, key_field="id")
            if match_admin_id:
                details = service.get_match_details(match_admin_id)
                rounds = details["rounds"]
                if not rounds:
                    st.info("Aucun round dans cette session.")
                else:
                    st.markdown("Rounds (supprimez pour corriger une saisie) :")
                    fmt_players = lambda ids: ", ".join(player_lookup.get(pid, pid) for pid in ids)
                    for rd in rounds:
                        cols = st.columns([2, 4, 3, 2])
                        cols[0].markdown(f"**Round {rd.index + 1}**")
                        cols[1].write(
                            f"{rd.teams[0].side_id}: {fmt_players(rd.teams[0].player_ids)} / "
                            f"{rd.teams[1].side_id}: {fmt_players(rd.teams[1].player_ids)}"
                        )
                        cols[2].write(f"Outcome: {rd.outcome.data}")
                        if cols[3].button("Supprimer", key=f"del-{rd.id}"):
                            service.delete_round(rd.id)
                            st.success("Round supprimé et ratings recalculés.")
                            st.rerun()


if __name__ == "__main__":
    page_home()
