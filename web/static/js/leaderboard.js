async function loadLeaderboard() {
  const resp = await fetch('/api/leaderboard');
  const data = await resp.json();

  // Stats bar
  const statsBar = document.getElementById('stats-bar');
  if (data.scored) {
    // Count total games entered across all rounds
    const totalEntered = (data.round_progress || []).reduce((sum, r) => sum + r.games_entered, 0);
    const totalGames = (data.round_progress || []).reduce((sum, r) => sum + r.games_total, 0);

    let parts = [
      `<span class="stat-item">Round: <span class="stat-value">${data.round_name}</span></span>`,
      `<span class="stat-item">Games Scored: <span class="stat-value">${totalEntered}/${totalGames}</span></span>`,
      `<span class="stat-item">Brackets: <span class="stat-value">${data.total_brackets.toLocaleString()}</span></span>`,
    ];
    if (data.perfect_count > 0) {
      parts.push(`<span class="stat-item">Perfect: <span class="stat-value text-green">${data.perfect_count.toLocaleString()}</span></span>`);
    }
    statsBar.innerHTML = parts.join('');
  } else {
    statsBar.innerHTML = `<span class="stat-item">Brackets: <span class="stat-value">${data.total_brackets.toLocaleString()}</span></span>` +
      `<span class="stat-item" style="color: var(--text-muted)">No rounds scored yet</span>`;
  }

  // Table
  const tbody = document.getElementById('leaderboard-body');
  tbody.innerHTML = '';

  data.brackets.forEach(b => {
    const tr = document.createElement('tr');
    tr.onclick = () => window.location.href = `/bracket/${b.bracket_id}`;

    const pct = b.pct_correct != null ? b.pct_correct * 100 : 0;
    const pctClass = pct >= 70 ? 'pct-high' : pct >= 40 ? 'pct-mid' : 'pct-low';
    const pctText = b.pct_correct != null ? pct.toFixed(1) + '%' : '-';
    const correctText = b.correct_picks != null
      ? `${b.correct_picks}/${b.total_scored_games}`
      : '-';
    const badge = b.is_perfect ? '<span class="badge-perfect">Perfect</span>' : '';

    tr.innerHTML = `
      <td class="col-rank">${b.rank ?? '-'}</td>
      <td class="col-id">${b.bracket_id}</td>
      <td class="col-pts">${b.total_points ?? '-'}</td>
      <td class="col-potential">${b.potential_points ?? '-'}</td>
      <td class="col-correct">${correctText}</td>
      <td class="col-accuracy">
        <div class="accuracy-cell">
          <div class="pct-bar-container">
            <div class="pct-bar-fill ${pctClass}" style="width: ${pct}%"></div>
          </div>
          <span class="pct-text">${pctText}</span>
          ${badge}
        </div>
      </td>
    `;

    tbody.appendChild(tr);
  });
}

loadLeaderboard();
