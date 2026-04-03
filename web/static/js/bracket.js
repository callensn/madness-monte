// Extract bracket_id from URL path: /bracket/b_00001
const bracketId = window.location.pathname.split('/').pop();

const ROUND_NAMES = {
  1: 'R64', 2: 'R32', 3: 'S16', 4: 'E8', 5: 'F4', 6: 'CHAMP',
};

// Region placement: matches FINAL_FOUR_PAIRS = [("East","West"), ("South","Midwest")]
// Left half top: East, Left half bottom: South
// Right half top: West, Right half bottom: Midwest
const LAYOUT = {
  'top-left':    'East',
  'bottom-left': 'South',
  'top-right':   'West',
  'bottom-right':'Midwest',
};

function createGameSlot(game) {
  const slot = document.createElement('div');
  slot.className = `game-slot ${game.status}`;

  // Empty placeholder: no teams known yet
  if (!game.home || !game.away) {
    slot.innerHTML = `
      <div class="team-line empty-team"><span class="name">TBD</span></div>
      <div class="team-line empty-team"><span class="name">TBD</span></div>
    `;
    return slot;
  }

  // Upcoming games: teams known but no winner yet
  if (!game.winner) {
    slot.innerHTML = `
      <div class="team-line">
        <span class="seed">${game.home.seed}</span>
        <span class="name">${game.home.name}</span>
      </div>
      <div class="team-line">
        <span class="seed">${game.away.seed}</span>
        <span class="name">${game.away.name}</span>
      </div>
    `;
    return slot;
  }

  const homeIsWinner = game.winner.seed === game.home.seed
    && game.winner.region === game.home.region;
  const awayIsWinner = !homeIsWinner;

  slot.innerHTML = `
    <div class="team-line ${homeIsWinner ? 'is-winner' : 'is-loser'}">
      <span class="seed">${game.home.seed}</span>
      <span class="name">${game.home.name}</span>
    </div>
    <div class="team-line ${awayIsWinner ? 'is-winner' : 'is-loser'}">
      <span class="seed">${game.away.seed}</span>
      <span class="name">${game.away.name}</span>
    </div>
    ${game.status === 'incorrect' && game.actual_winner
      ? `<div class="actual-winner-hint">Actual: (${game.actual_winner.seed}) ${game.actual_winner.name}</div>`
      : ''}
  `;

  return slot;
}

function renderRegion(containerId, regionData, direction) {
  const container = document.getElementById(containerId);
  if (!regionData) {
    container.textContent = 'No data';
    return;
  }

  // For LTR regions: rounds 1,2,3,4 (left to right)
  // For RTL regions: rounds 4,3,2,1 (reversed so R1 is on the outside)
  const roundOrder = direction === 'ltr' ? [1, 2, 3, 4] : [4, 3, 2, 1];

  roundOrder.forEach(roundNum => {
    const col = document.createElement('div');
    col.className = 'round-column';

    // Round header
    const header = document.createElement('div');
    header.className = 'round-header';
    header.textContent = ROUND_NAMES[roundNum];
    col.appendChild(header);

    const games = regionData[String(roundNum)] || [];
    // Sort by game_index to ensure proper ordering
    games.sort((a, b) => a.game_index - b.game_index);

    games.forEach(game => {
      col.appendChild(createGameSlot(game));
    });

    container.appendChild(col);
  });
}

function renderFinalFour(data) {
  // Sort by game_index to ensure proper order
  const ff = (data.final_four || []).sort((a, b) => a.game_index - b.game_index);
  const champ = (data.championship || []).sort((a, b) => a.game_index - b.game_index);

  // FF Game 0: East winner vs West winner
  const ff0Container = document.getElementById('ff-game-0');
  if (ff.length > 0) {
    const label = document.createElement('div');
    label.className = 'ff-label';
    label.textContent = 'Final Four';
    ff0Container.appendChild(label);
    ff0Container.appendChild(createGameSlot(ff[0]));
  }

  // FF Game 1: South winner vs Midwest winner
  const ff1Container = document.getElementById('ff-game-1');
  if (ff.length > 1) {
    const label = document.createElement('div');
    label.className = 'ff-label';
    label.textContent = 'Final Four';
    ff1Container.appendChild(label);
    ff1Container.appendChild(createGameSlot(ff[1]));
  }

  // Championship
  const champContainer = document.getElementById('championship');
  if (champ.length > 0) {
    const label = document.createElement('div');
    label.className = 'champ-label';
    label.textContent = 'Championship';
    champContainer.appendChild(label);
    champContainer.appendChild(createGameSlot(champ[0]));

    // Champion name banner (only if there's a winner)
    const winner = champ[0].winner;
    if (winner) {
      const banner = document.createElement('div');
      banner.className = 'champion-banner';
      banner.textContent = `Champion: ${winner.name}`;
      champContainer.appendChild(banner);
    }
  }
}

function renderHeader(data) {
  const header = document.getElementById('bracket-header');

  if (data.is_current) {
    let parts = [`<span class="bracket-id">Current Tournament Bracket</span>`];
    if (data.round_progress) {
      const totalEntered = data.round_progress.reduce((sum, r) => sum + r.games_entered, 0);
      const totalGames = data.round_progress.reduce((sum, r) => sum + r.games_total, 0);
      parts.push(`<span class="accuracy-text">${totalEntered}/${totalGames} games played</span>`);
    }
    header.innerHTML = parts.join('');
    document.title = 'Current Tournament Bracket';
    return;
  }

  let parts = [`<span class="bracket-id">${data.bracket_id}</span>`];

  if (data.score) {
    parts.push(`<span class="score-pill">${data.score.total_points} pts</span>`);
    parts.push(`<span class="accuracy-text">${data.score.correct_picks}/${data.score.total_scored_games} correct (${(data.score.pct_correct * 100).toFixed(1)}%)</span>`);
    if (data.score.rank) {
      parts.push(`<span class="rank-badge">Rank #${data.score.rank}</span>`);
    }
    if (data.score.is_perfect) {
      parts.push(`<span class="badge-perfect">Perfect</span>`);
    }
  } else {
    parts.push(`<span class="accuracy-text text-muted">No rounds scored yet</span>`);
  }

  header.innerHTML = parts.join('');
}

async function loadBracket() {
  const resp = await fetch(`/api/bracket/${bracketId}`);
  if (!resp.ok) {
    document.getElementById('bracket-container').innerHTML =
      `<p style="padding: 40px; color: var(--red);">Bracket "${bracketId}" not found.</p>`;
    return;
  }

  const data = await resp.json();

  renderHeader(data);

  // Render region labels
  for (const [pos, region] of Object.entries(LAYOUT)) {
    const labelEl = document.getElementById(`label-${pos}`);
    if (labelEl) labelEl.textContent = region;
  }

  // Render regions
  renderRegion('region-top-left',    data.regions['East'],    'ltr');
  renderRegion('region-bottom-left', data.regions['South'],   'ltr');
  renderRegion('region-top-right',   data.regions['West'],    'rtl');
  renderRegion('region-bottom-right',data.regions['Midwest'], 'rtl');

  // Render Final Four + Championship
  renderFinalFour(data);
}

loadBracket();
