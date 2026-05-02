/**
 * Safari — Frontend Application
 * ==============================
 * Handles map, calendar, form interactions, and API calls.
 */

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
    budget: 3000,
    currency: 'SAR',
    origin: 'riyadh',
    destination: 'coast',
    travelMode: 'car',
    vehicleType: 'default',
    days: 4,
    tripData: null,
};

// ─── Map Setup ───────────────────────────────────────────────────────────────
const map = L.map('map', {
    center: [24.0, 44.0],
    zoom: 6,
    zoomControl: false,
});

L.control.zoom({ position: 'topright' }).addTo(map);

// Dark map tiles
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
}).addTo(map);

let routeLine = null;
let markers = [];

const CITY_COORDS = {};

// Load coordinates on start
fetch('/api/coords')
    .then(r => r.json())
    .then(data => Object.assign(CITY_COORDS, data));

// ─── DOM Elements ────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const budgetInput = $('budget-input');
const budgetSlider = $('budget-slider');
const budgetDisplay = $('budget-display');
const currencySelect = $('currency-select');
const originSelect = $('origin-select');
const vehicleSelect = $('vehicle-select');
const vehicleGroup = $('vehicle-group');
const daysValue = $('days-value');
const daysMinus = $('days-minus');
const daysPlus = $('days-plus');
const planBtn = $('plan-btn');
const tripForm = $('trip-form');
const loadingOverlay = $('loading-overlay');

// Map overlays
const tripInfo = $('trip-info');
const budgetBar = $('budget-bar');

// Right panel
const itineraryList = $('itinerary-list');
const budgetDetails = $('budget-details');
const budgetTable = $('budget-table');
const warningsBox = $('warnings-box');

// ─── Format Number ───────────────────────────────────────────────────────────
function fmt(n) {
    return Math.round(n).toLocaleString('en-US');
}

// ─── Budget Input Sync ──────────────────────────────────────────────────────
budgetInput.addEventListener('input', () => {
    const v = parseInt(budgetInput.value) || 500;
    state.budget = v;
    budgetSlider.value = Math.min(v, 15000);
    budgetDisplay.textContent = fmt(v);
});

budgetSlider.addEventListener('input', () => {
    const v = parseInt(budgetSlider.value);
    state.budget = v;
    budgetInput.value = v;
    budgetDisplay.textContent = fmt(v);
});

currencySelect.addEventListener('change', () => {
    state.currency = currencySelect.value;
});

originSelect.addEventListener('change', () => {
    state.origin = originSelect.value;
});

vehicleSelect.addEventListener('change', () => {
    state.vehicleType = vehicleSelect.value;
});

// ─── Vibe Cards ──────────────────────────────────────────────────────────────
document.querySelectorAll('.vibe-card').forEach(card => {
    card.addEventListener('click', () => {
        document.querySelectorAll('.vibe-card').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        state.destination = card.dataset.vibe;
    });
});

// ─── Travel Mode ─────────────────────────────────────────────────────────────
document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.travelMode = btn.dataset.mode;
        vehicleGroup.classList.toggle('hidden', btn.dataset.mode !== 'car');
    });
});

// ─── Days ────────────────────────────────────────────────────────────────────
daysMinus.addEventListener('click', () => {
    if (state.days > 1) {
        state.days--;
        daysValue.textContent = state.days;
    }
});

daysPlus.addEventListener('click', () => {
    if (state.days < 30) {
        state.days++;
        daysValue.textContent = state.days;
    }
});

// ─── Calendar ────────────────────────────────────────────────────────────────
function renderCalendar(tripStartDay, tripDays) {
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth();
    const today = now.getDate();

    const startDay = tripStartDay || today + 1;

    $('cal-month').textContent = now.toLocaleString('en-US', { month: 'long', year: 'numeric' });

    const firstDayOfMonth = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();

    const grid = $('cal-grid');
    grid.innerHTML = '';

    // Day headers
    ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].forEach(d => {
        const cell = document.createElement('div');
        cell.className = 'cal-cell header';
        cell.textContent = d;
        grid.appendChild(cell);
    });

    // Empty cells before first day
    for (let i = 0; i < firstDayOfMonth; i++) {
        const cell = document.createElement('div');
        cell.className = 'cal-cell';
        grid.appendChild(cell);
    }

    // Day cells
    for (let d = 1; d <= daysInMonth; d++) {
        const cell = document.createElement('div');
        cell.className = 'cal-cell';
        cell.textContent = d;

        if (d === today) cell.classList.add('today');

        if (tripDays > 0) {
            const tripEnd = startDay + tripDays - 1;
            if (d >= startDay && d <= tripEnd) {
                const relativeDay = d - startDay + 1;
                cell.classList.add('trip-day');
                cell.style.cursor = 'pointer';
                cell.title = `Scroll to Day ${relativeDay}`;
                cell.onclick = () => {
                    const targetCard = document.getElementById(`day-card-${relativeDay}`);
                    if (targetCard) {
                        targetCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        // Add temporary highlight effect
                        targetCard.style.boxShadow = '0 0 20px var(--accent)';
                        setTimeout(() => targetCard.style.boxShadow = '', 1000);
                    }
                };
                if (d === startDay) cell.classList.add('trip-start');
                if (d === tripEnd) cell.classList.add('trip-end');
            }
        }

        grid.appendChild(cell);
    }
}

// Initial calendar
renderCalendar(null, 0);

// ─── Map Helpers ─────────────────────────────────────────────────────────────
function clearMap() {
    markers.forEach(m => map.removeLayer(m));
    markers = [];
    if (routeLine) {
        map.removeLayer(routeLine);
        routeLine = null;
    }
}

function createIcon(emoji) {
    return L.divIcon({
        className: 'custom-marker',
        html: `<span style="font-size:28px;filter:drop-shadow(0 2px 4px rgba(0,0,0,0.6))">${emoji}</span>`,
        iconSize: [36, 36],
        iconAnchor: [18, 18],
    });
}

function drawRoute(originCoords, destCoords, originName, destName, data) {
    clearMap();

    const oLatLng = [originCoords.lat, originCoords.lng];
    const dLatLng = [destCoords.lat, destCoords.lng];

    const waypoints = [oLatLng];

    // Origin marker
    const originMarker = L.marker(oLatLng, { icon: createIcon('📍') })
        .addTo(map)
        .bindPopup(`
            <div class="popup-title">${originName}</div>
            <div class="popup-detail">Starting point</div>
        `);
    markers.push(originMarker);

    // Hospitality markers (Hotels & Restaurants from Agent 2)
    let addedHospitality = false;
    if (data.hospitality) {
        if (data.hospitality.hotels && data.hospitality.hotels.length > 0) {
            data.hospitality.hotels.forEach(h => {
                if (h.lat && h.lng) {
                    const hLatLng = [h.lat, h.lng];
                    waypoints.push(hLatLng);
                    const hotelMarker = L.marker(hLatLng, { icon: createIcon('🏨') })
                        .addTo(map)
                        .bindPopup(`
                            <div class="popup-title">${h.name}</div>
                            <div class="popup-detail">${h.stars}★ Hotel</div>
                            <div class="popup-detail" style="color:var(--accent);">~${h.best_deal ? h.best_deal.final_price_sar : 0} SAR/night</div>
                        `);
                    markers.push(hotelMarker);
                    addedHospitality = true;
                }
            });
        }
        if (data.hospitality.restaurants && data.hospitality.restaurants.length > 0) {
            data.hospitality.restaurants.forEach(r => {
                if (r.lat && r.lng) {
                    const rLatLng = [r.lat, r.lng];
                    const rMarker = L.marker(rLatLng, { icon: createIcon('🍽️') })
                        .addTo(map)
                        .bindPopup(`
                            <div class="popup-title">${r.name}</div>
                            <div class="popup-detail">${r.cuisine} | ★${r.rating}</div>
                        `);
                    markers.push(rMarker);
                }
            });
        }
    }

    // Fallbacks if no hospitality data
    if (!addedHospitality) {
        const hotel = data.activities.hotel;
        if (hotel && hotel.lat && hotel.lng) {
            const hLatLng = [hotel.lat, hotel.lng];
            waypoints.push(hLatLng);
            const hotelMarker = L.marker(hLatLng, { icon: createIcon('🏨') })
                .addTo(map)
                .bindPopup(`
                    <div class="popup-title">${hotel.name}</div>
                    <div class="popup-detail">Recommended Hotel</div>
                `);
            markers.push(hotelMarker);
        } else {
            waypoints.push(dLatLng);
            // Destination marker fallback
            const destEmoji = { coast: '🏖️', mountains: '⛰️', desert: '🏜️', city: '🏙️' };
            const emoji = destEmoji[state.destination] || '📌';
            const destMarker = L.marker(dLatLng, { icon: createIcon(emoji) })
                .addTo(map)
                .bindPopup(`
                    <div class="popup-title">${destName}</div>
                    <div class="popup-detail">${data.activities.vibe}</div>
                    <div class="popup-detail">${fmt(data.transport.distance_km)} km from ${originName}</div>
                `);
            markers.push(destMarker);
        }
    }

    // Activity markers
    const daily = data.activities.daily_plan;
    Object.keys(daily).forEach(day => {
        daily[day].forEach(act => {
            if (act && act.lat && act.lng) {
                const aLatLng = [act.lat, act.lng];
                waypoints.push(aLatLng);
                const isEvent = act.is_live_event;
                const isTrending = act.is_trending_spot;
                let icon, typeStr;
                if (isEvent) {
                    icon = '🎪';
                    typeStr = 'Live Event';
                } else if (isTrending) {
                    icon = '🔥';
                    typeStr = 'Trending Spot';
                } else {
                    icon = '🎯';
                    typeStr = 'Activity';
                }
                const timeStr = ((isEvent || isTrending) && act.time && act.time !== "TBD") 
                    ? `<div class="popup-detail" style="color:var(--accent); font-weight:bold; margin-top:4px;">🕒 Starts at: ${act.time}</div>` 
                    : '';
                const buzzStr = (isTrending && act.social_buzz)
                    ? `<div class="popup-detail" style="color:#f59e0b; margin-top:4px;">📱 ${act.social_buzz}</div>`
                    : '';
                const ratingStr = (isTrending && act.rating)
                    ? `<div class="popup-detail" style="margin-top:2px;">${'⭐'.repeat(Math.round(act.rating))} (${act.rating})</div>`
                    : '';
                const actMarker = L.marker(aLatLng, { icon: createIcon(icon) })
                    .addTo(map)
                    .bindPopup(`
                        <div class="popup-title">${act.name}</div>
                        <div class="popup-detail">${typeStr} (Day ${day})</div>
                        ${timeStr}
                        ${buzzStr}
                        ${ratingStr}
                    `);
                markers.push(actMarker);
            }
        });
    });

    // Route line connecting everything
    routeLine = L.polyline(waypoints, {
        color: '#8b5cf6',
        weight: 4,
        opacity: 0.8,
        dashArray: '10, 10',
    }).addTo(map);

    // Fit bounds to all waypoints
    const bounds = L.latLngBounds(waypoints);
    map.fitBounds(bounds, { padding: [80, 80] });
}

// ─── Generate Activity Times ────────────────────────────────────────────────
function getActivitySchedule(dayNum, activities, isFirstDay, isLastDay) {
    const schedule = [];
    let hour = 8;

    if (isFirstDay) {
        schedule.push({ time: '06:00', icon: '🚗', text: `Depart from ${state.origin.charAt(0).toUpperCase() + state.origin.slice(1)}` });
        hour = 14;
    }

    activities.forEach(act => {
        const isObj = typeof act === 'object';
        const name = isObj ? act.name : act;
        const isEvent = isObj && act.is_live_event;
        const isTrending = isObj && act.is_trending_spot;
        let icon;
        if (isEvent) icon = '🎪';
        else if (isTrending) icon = '🔥';
        else icon = '🎯';
        const time = ((isEvent || isTrending) && act.time && act.time !== "TBD") ? act.time : `${String(hour).padStart(2, '0')}:00`;
        const id = isObj ? act.id : null;
        const cost = isObj ? act.cost : 0;
        const whyGo = isObj ? act.why_go : '';
        const reviews = isObj ? act.reviews : [];
        const reviewCount = isObj ? act.review_count : 0;
        
        schedule.push({ time, icon, text: name, id, isEvent, isTrending, cost, dayNum, socialBuzz: isObj ? act.social_buzz : '', rating: isObj ? act.rating : 0, whyGo, reviews, reviewCount });
        hour += isLastDay ? 2 : 3;
    });

    if (isLastDay) {
        schedule.push({ time: `${String(Math.min(hour, 16)).padStart(2, '0')}:00`, icon: '🚗', text: `Return trip home` });
    }

    return schedule;
}

// ─── Render Itinerary ────────────────────────────────────────────────────────
function renderItinerary(data) {
    itineraryList.innerHTML = '';

    const days = data.budget.days;
    const daily = data.activities.daily_plan;
    const currency = data.budget.currency;
    const perDay = data.budget.lodging.per_day + data.budget.food.per_day + data.budget.activities.per_day;

    for (let d = 1; d <= days; d++) {
        const acts = daily[String(d)] || [];
        const isFirst = d === 1;
        const isLast = d === days;
        const schedule = getActivitySchedule(d, acts, isFirst, isLast);

        const card = document.createElement('div');
        card.className = 'day-card';
        card.id = `day-card-${d}`;
        card.style.animationDelay = `${d * 0.08}s`;

        let activitiesHtml = schedule.map((s, index) => {
            const buzzTag = (s.isTrending && s.socialBuzz) ? `<div class="social-buzz-tag">📱 ${s.socialBuzz}</div>` : '';
            const deleteBtn = (s.isEvent || s.isTrending) ? `<button type="button" class="delete-btn" onclick="deleteEvent('${s.dayNum}', '${s.id}', ${s.cost})" title="Remove">🗑️</button>` : '';
            
            let legHtml = '';
            if (data.timeline && data.timeline[String(d)] && data.timeline[String(d)].legs) {
                const legs = data.timeline[String(d)].legs;
                if (index < legs.length) {
                    const leg = legs[index];
                    legHtml = `
                    <div class="transit-leg" style="margin-left: 20px; padding: 5px 10px; border-left: 2px dashed rgba(255,255,255,0.2); font-size: 1.1em; color: #a1a1aa;">
                        <span>${leg.mode}</span> | <span>${leg.dist.toFixed(1)} km</span> | <span>Cost: ${leg.cost.toFixed(0)} ${currency}</span>
                    </div>`;
                }
            }

            let reviewsHtml = '';
            if (s.whyGo || (s.reviews && s.reviews.length > 0)) {
                reviewsHtml = `<div class="activity-reviews-panel" style="margin-top: 10px; padding: 12px; background: rgba(0,0,0,0.15); border-radius: 8px;">`;
                if (s.rating) {
                    reviewsHtml += `<div style="color:#fbbf24; font-weight:bold; margin-bottom:6px;">⭐ ${s.rating} (${s.reviewCount} reviews)</div>`;
                }
                if (s.whyGo) {
                    reviewsHtml += `<div style="font-size:0.95em; color:var(--text-secondary); margin-bottom:8px;"><em>Why go:</em> ${s.whyGo}</div>`;
                }
                if (s.reviews && s.reviews.length > 0) {
                    const rev = s.reviews[0]; // Show top review
                    reviewsHtml += `<div style="font-size:0.9em; border-left:2px solid var(--accent); padding-left:8px; color:#cbd5e1;">
                        " ${rev.text} " <br><span style="opacity:0.6;font-size:0.85em;">— ${rev.user} (⭐ ${rev.rating})</span>
                    </div>`;
                }
                reviewsHtml += `</div>`;
            }

            return `
            ${legHtml}
            <div class="activity-item ${s.isTrending ? 'trending-item' : ''} ${s.isEvent ? 'event-item' : ''}" style="align-items:flex-start; flex-direction:column;">
                <div style="display:flex; width:100%;">
                    <span class="activity-time">${s.time}</span>
                    <span class="activity-icon">${s.icon}</span>
                    <div style="flex:1">
                        <span>${s.text}</span>
                        ${buzzTag}
                    </div>
                    ${deleteBtn}
                </div>
                ${reviewsHtml}
            </div>
            `;
        }).join('');
        
        // Add return to hotel leg if it exists
        if (data.timeline && data.timeline[String(d)] && data.timeline[String(d)].legs) {
            const legs = data.timeline[String(d)].legs;
            if (schedule.length < legs.length) {
                const leg = legs[legs.length - 1];
                activitiesHtml += `
                <div class="transit-leg" style="margin-left: 20px; padding: 5px 10px; border-left: 2px dashed rgba(255,255,255,0.2); font-size: 1.1em; color: #a1a1aa;">
                    <span>${leg.mode}</span> | <span>${leg.dist.toFixed(1)} km</span> | <span>Cost: ${leg.cost.toFixed(0)} ${currency}</span>
                </div>`;
            }
        }
        
        let recommendationHtml = '';
        if (data.timeline && data.timeline[String(d)] && data.timeline[String(d)].recommendation) {
            recommendationHtml = `
                <div style="margin-top: 10px; padding: 12px; background: rgba(59, 130, 246, 0.1); border-left: 3px solid #3b82f6; font-size: 1.1em; border-radius: 4px; line-height: 1.5;">
                    ${data.timeline[String(d)].recommendation}
                </div>
            `;
        }

        // Add lodging and food info
        activitiesHtml += `
            ${recommendationHtml}
            <div class="activity-item" style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.05)">
                <span class="activity-time"></span>
                <span class="activity-icon">🏨</span>
                <span>Lodging: ~${fmt(data.budget.lodging.per_day)} ${currency}</span>
            </div>
            <div class="activity-item">
                <span class="activity-time"></span>
                <span class="activity-icon">🍽️</span>
                <span>Meals: ~${fmt(data.budget.food.per_day)} ${currency}</span>
            </div>
        `;

        card.innerHTML = `
            <div class="day-header">
                <span class="day-number">Day ${d}${isFirst ? ' — Departure' : isLast ? ' — Return' : ''}</span>
                <span class="day-budget">~${fmt(perDay)} ${currency}</span>
            </div>
            <div class="day-activities">${activitiesHtml}</div>
        `;

        itineraryList.appendChild(card);
    }
}

// ─── Render Budget Details ───────────────────────────────────────────────────
function renderBudgetDetails(data) {
    const b = data.budget;
    const c = b.currency;

    budgetTable.innerHTML = `
        <div class="budget-row">
            <span class="budget-row-label">🚗 Transport (round-trip)</span>
            <span class="budget-row-value">${fmt(b.transport)} ${c}</span>
        </div>
        <div class="budget-row">
            <span class="budget-row-label">🏨 Lodging (${b.days} nights)</span>
            <span class="budget-row-value">${fmt(b.lodging.total)} ${c}</span>
        </div>
        <div class="budget-row">
            <span class="budget-row-label">🍽️ Food (${b.days} days)</span>
            <span class="budget-row-value">${fmt(b.food.total)} ${c}</span>
        </div>
        <div class="budget-row">
            <span class="budget-row-label">🎯 Activities (${b.days} days)</span>
            <span class="budget-row-value">${fmt(b.activities.total)} ${c}</span>
        </div>
        <div class="budget-row">
            <span class="budget-row-label">🛡️ Emergency Buffer</span>
            <span class="budget-row-value">${fmt(b.buffer.total)} ${c}</span>
        </div>
        <div class="budget-row total">
            <span class="budget-row-label">Total Budget</span>
            <span class="budget-row-value">${fmt(b.total)} ${c}</span>
        </div>
        <div class="budget-vis-bar">
            <div class="vis-segment" style="width:${(b.transport/b.total*100).toFixed(1)}%;background:var(--color-transport)"></div>
            <div class="vis-segment" style="width:${(b.lodging.total/b.total*100).toFixed(1)}%;background:var(--color-lodging)"></div>
            <div class="vis-segment" style="width:${(b.food.total/b.total*100).toFixed(1)}%;background:var(--color-food)"></div>
            <div class="vis-segment" style="width:${(b.activities.total/b.total*100).toFixed(1)}%;background:var(--color-activities)"></div>
            <div class="vis-segment" style="width:${(b.buffer.total/b.total*100).toFixed(1)}%;background:var(--color-buffer)"></div>
        </div>
    `;

    budgetDetails.classList.remove('hidden');
}

// ─── Update Map Overlays ────────────────────────────────────────────────────
function updateOverlays(data) {
    // Trip info card
    $('info-origin').textContent = data.map.origin_name;
    $('info-dest').textContent = data.map.dest_name;
    $('info-distance').textContent = fmt(data.transport.distance_km);
    $('info-days').textContent = data.budget.days;
    $('info-cost').textContent = fmt(data.budget.total);
    $('info-currency').textContent = data.budget.currency;
    tripInfo.classList.remove('hidden');

    // Budget bar segments
    const c = data.budget.currency;
    $('val-transport').textContent = `${fmt(data.budget.transport)} ${c}`;
    $('val-lodging').textContent = `${fmt(data.budget.lodging.total)} ${c}`;
    $('val-food').textContent = `${fmt(data.budget.food.total)} ${c}`;
    $('val-activities').textContent = `${fmt(data.budget.activities.total)} ${c}`;
    $('val-buffer').textContent = `${fmt(data.budget.buffer.total)} ${c}`;
    budgetBar.classList.remove('hidden');
}

// ─── Warnings ────────────────────────────────────────────────────────────────
function renderWarnings(data) {
    const warnings = data.budget.warnings || [];
    if (warnings.length === 0) {
        warningsBox.classList.add('hidden');
        return;
    }
    warningsBox.classList.remove('hidden');
    warningsBox.innerHTML = warnings.map(w => `
        <div class="warning-item">⚠️ ${w}</div>
    `).join('');
}

// ─── Plan Trip ───────────────────────────────────────────────────────────────
async function planTrip() {
    loadingOverlay.classList.remove('hidden');

    const payload = {
        budget: state.budget,
        currency: state.currency,
        origin: state.origin,
        destination: state.destination,
        travel_mode: state.travelMode,
        vehicle_type: state.vehicleType,
        days: state.days,
        interests: $('interests-input').value,
    };

    try {
        const response = await fetch('/api/plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || 'Planning failed');
        }

        const data = await response.json();
        state.paths = data.paths;
        state.recommendation = data.recommendation;
        
        // Show path selection
        renderPathSelection(data.paths, data.recommendation);

    } catch (err) {
        alert('Safari encountered an error: ' + err.message);
    } finally {
        loadingOverlay.classList.add('hidden');
    }
}

// ─── Path Selection ──────────────────────────────────────────────────────────
function renderPathSelection(paths, recommendationIdx) {
    const grid = $('paths-grid');
    grid.innerHTML = '';
    
    paths.forEach((path, idx) => {
        const isRec = idx === recommendationIdx;
        const b = path.budget;
        const c = b.currency;
        
        let features = '';
        if (path.path_type === 'budget') {
            features = `<li>💰 Focused on free activities</li><li>🚌 Prioritizes public transit</li><li>🏨 Budget accommodations</li>`;
        } else if (path.path_type === 'balanced') {
            features = `<li>⚖️ Mix of free & paid activities</li><li>🚗 Comfortable transport</li><li>🏨 Mid-range hotels</li>`;
        } else {
            features = `<li>✨ Premium activities</li><li>🚕 Max convenience transport</li><li>🏨 Luxury accommodations</li>`;
        }

        const card = document.createElement('div');
        card.className = `path-card ${isRec ? 'recommended' : ''}`;
        card.innerHTML = `
            <h3>${path.path_type} Path</h3>
            <div class="path-budget">~${fmt(b.total)} ${c}</div>
            <ul class="path-features">${features}</ul>
        `;
        card.addEventListener('click', () => selectPath(idx));
        grid.appendChild(card);
    });

    $('path-selection-overlay').classList.remove('hidden');
}

$('cancel-path-selection').addEventListener('click', () => {
    $('path-selection-overlay').classList.add('hidden');
});

function selectPath(idx) {
    $('path-selection-overlay').classList.add('hidden');
    
    // Switch panels
    $('trip-form').classList.add('hidden');
    $('results-panel').classList.remove('hidden');

    const data = state.paths[idx];
    state.tripData = data;

    // Draw map route
    drawRoute(data.map.origin, data.map.destination, data.map.origin_name, data.map.dest_name, data);

    // Update overlays
    updateOverlays(data);

    // Render itinerary (Right Panel)
    renderItinerary(data);

    // Render left panel results
    renderHospitalityDeals(data);
    renderWebResearch(data);
    renderBudgetDetailsLeft(data); // Render budget in left panel too

    // Render warnings
    renderWarnings(data);

    // Update calendar
    const today = new Date().getDate();
    renderCalendar(today + 1, state.days);
}

$('edit-trip-btn').addEventListener('click', () => {
    $('results-panel').classList.add('hidden');
    $('trip-form').classList.remove('hidden');
});

function renderBudgetDetailsLeft(data) {
    const b = data.budget;
    const c = b.currency;
    const container = $('left-budget');
    if(!container) return;
    
    container.innerHTML = `
        <h3 style="margin-top:20px;margin-bottom:15px;color:var(--text-primary);font-size:22px;">💰 Budget Breakdown</h3>
        <div class="budget-row"><span class="budget-row-label">🚗 Transport</span><span class="budget-row-value">${fmt(b.transport)} ${c}</span></div>
        <div class="budget-row"><span class="budget-row-label">🏨 Lodging</span><span class="budget-row-value">${fmt(b.lodging.total)} ${c}</span></div>
        <div class="budget-row"><span class="budget-row-label">🍽️ Food</span><span class="budget-row-value">${fmt(b.food.total)} ${c}</span></div>
        <div class="budget-row"><span class="budget-row-label">🎯 Activities</span><span class="budget-row-value">${fmt(b.activities.total)} ${c}</span></div>
        <div class="budget-row"><span class="budget-row-label">🛡️ Buffer</span><span class="budget-row-value">${fmt(b.buffer.total)} ${c}</span></div>
        <div class="budget-row total" style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.1);font-weight:bold;font-size:18px;">
            <span class="budget-row-label">Total</span>
            <span class="budget-row-value">${fmt(b.total)} ${c}</span>
        </div>
    `;
}

// ─── Render Hospitality Deals ────────────────────────────────────────────────
function renderHospitalityDeals(data) {
    const container = $('left-hospitality');
    if (!container) return;

    if (!data.hospitality || (!data.hospitality.hotels.length && !data.hospitality.restaurants.length)) {
        container.innerHTML = '';
        return;
    }

    let html = '<h3 style="margin-bottom:15px;color:var(--text-primary);font-size:22px;">🏨 Recommended Places</h3>';

    if (data.hospitality.hotels && data.hospitality.hotels.length > 0) {
        html += `<div style="margin-bottom: 10px;"><strong>🏨 Hotels</strong></div>`;
        data.hospitality.hotels.slice(0, 3).forEach(h => {
            const bd = h.best_deal;
            html += `
                <div style="margin-bottom: 8px; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 4px;">
                    <div><strong>${h.name}</strong> (${h.stars}★)</div>
                    <div style="display:flex; justify-content:space-between; margin-top:4px;">
                        <span style="text-decoration: line-through; opacity: 0.6;">${bd.base_price_sar} SAR</span>
                        <span style="color: #4ade80; font-weight:bold;">${bd.final_price_sar} SAR</span>
                        <span style="color: var(--accent);">-${bd.discount_percent}% OFF</span>
                    </div>
                </div>
            `;
        });
    }

    if (data.hospitality.restaurants && data.hospitality.restaurants.length > 0) {
        html += `<div style="margin-top: 15px; margin-bottom: 10px;"><strong>🍽️ Restaurants</strong></div>`;
        data.hospitality.restaurants.slice(0, 3).forEach(r => {
            html += `
                <div style="margin-bottom: 8px; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 4px;">
                    <div><strong>${r.name}</strong></div>
                    <div style="display:flex; justify-content:space-between; margin-top:4px; opacity:0.8;">
                        <span>★ ${r.rating}</span>
                        <span>Tables: ${r.available_tables}/${r.total_tables}</span>
                    </div>
                </div>
            `;
        });
    }

    container.innerHTML = html;
}

// ─── Render Web Research Panel ──────────────────────────────────────────────
function renderWebResearch(data) {
    const research = data.web_research;
    const container = $('left-research');
    if (!container) return;

    if (!research) {
        container.innerHTML = '';
        return;
    }

    let html = '';

    // Weather
    if (research.weather_summary) {
        html += `
            <div class="research-section weather-section">
                <div class="research-header">🌤️ Current Weather</div>
                <p class="research-text">${research.weather_summary}</p>
            </div>
        `;
    }

    // Social Media Posts
    if (research.social_posts && research.social_posts.length > 0) {
        const platformIcons = {
            'x/twitter': '🐦', 'instagram': '📸',
            'tiktok': '🎵', 'reddit': '🔴', 'blog': '📝'
        };
        const platformColors = {
            'x/twitter': '#1DA1F2', 'instagram': '#E1306C',
            'tiktok': '#00f2ea', 'reddit': '#FF4500', 'blog': '#10B981'
        };
        html += `<div class="research-section">`;
        html += `<div class="research-header">📱 Social Media Buzz</div>`;
        research.social_posts.forEach(post => {
            const icon = platformIcons[post.platform] || '🌐';
            const color = platformColors[post.platform] || '#888';
            html += `
                <div class="social-post">
                    <div class="social-post-header">
                        <span class="platform-badge" style="background:${color}20;color:${color};border:1px solid ${color}40">
                            ${icon} ${post.platform}
                        </span>
                        <span class="social-author">@${post.author}</span>
                    </div>
                    <p class="social-content">${post.content}</p>
                    <div class="social-meta">
                        <span class="social-category">${post.category}</span>
                        ${post.likes ? `<span class="social-likes">❤️ ${post.likes.toLocaleString()}</span>` : ''}
                    </div>
                </div>
            `;
        });
        html += `</div>`;
    }

    // Trending Spots
    if (research.trending_spots && research.trending_spots.length > 0) {
        html += `<div class="research-section">`;
        html += `<div class="research-header">🔥 Trending Spots</div>`;
        research.trending_spots.forEach(spot => {
            const stars = spot.rating ? '⭐'.repeat(Math.round(spot.rating)) + ` (${spot.rating})` : '';
            const tagsHtml = (spot.tags || []).map(t => `<span class="spot-tag">${t}</span>`).join('');
            html += `
                <div class="trending-spot-card">
                    <div class="spot-header">
                        <span class="spot-name">${spot.name}</span>
                        <span class="spot-price">${spot.price_range}</span>
                    </div>
                    <p class="spot-description">${spot.description}</p>
                    ${stars ? `<div class="spot-rating">${stars}</div>` : ''}
                    ${spot.social_buzz ? `<div class="spot-buzz">📱 ${spot.social_buzz}</div>` : ''}
                    <div class="spot-tags">${tagsHtml}</div>
                    <div class="spot-cost">~${fmt(spot.estimated_cost_sar)} ${data.budget.currency}</div>
                </div>
            `;
        });
        html += `</div>`;
    }

    // Local Tips
    if (research.local_insights && research.local_insights.length > 0) {
        html += `<div class="research-section">`;
        html += `<div class="research-header">💡 Local Tips from the Web</div>`;
        research.local_insights.forEach(tip => {
            const categoryIcons = {
                'money_saving': '💰', 'safety': '🛡️',
                'culture': '🕌', 'weather': '🌤️', 'transport': '🚗'
            };
            const icon = categoryIcons[tip.category] || '💡';
            html += `
                <div class="local-tip">
                    <span class="tip-icon">${icon}</span>
                    <div class="tip-content">
                        <p>${tip.tip}</p>
                        <span class="tip-source">${tip.source}</span>
                    </div>
                </div>
            `;
        });
        html += `</div>`;
    }

    container.innerHTML = `<h3 style="margin-top:20px;margin-bottom:15px;color:var(--text-primary);font-size:22px;">🌐 Online Discoveries</h3>` + html;
}

// ─── Form Submit ─────────────────────────────────────────────────────────────
tripForm.addEventListener('submit', (e) => {
    e.preventDefault();
    planTrip();
});

// ─── Delete Event ────────────────────────────────────────────────────────────
window.deleteEvent = function(day, actId, cost) {
    if (!state.tripData) return;
    const daily = state.tripData.activities.daily_plan;
    if (daily[day]) {
        const idx = daily[day].findIndex(a => a.id === actId);
        if (idx !== -1) {
            daily[day].splice(idx, 1);
            
            // Restore budget
            state.tripData.budget.activities.total += cost;
            state.tripData.budget.activities.per_day = state.tripData.budget.activities.total / state.tripData.budget.days;
            
            // Re-render
            renderItinerary(state.tripData);
            renderBudgetDetails(state.tripData);
            updateOverlays(state.tripData);
            drawRoute(state.tripData.map.origin, state.tripData.map.destination, state.tripData.map.origin_name, state.tripData.map.dest_name, state.tripData);
        }
    }
};
