# blackjack_streamlit_full_ui_modified.py
# Streamlit Blackjack — single player, full rules, side bets, graphical cards,
# animated chips, soft/hard display, and game info buttons.

import random
from dataclasses import dataclass, field
from datetime import datetime
import streamlit as st

# ───────── Money helpers ─────────
def to_cents(x: float) -> int:
    """Convert dollars to integer cents."""
    return int(round(float(x) * 100))

def fmt(cents: int) -> str:
    """Format integer cents as $D.CC string."""
    return f"${cents/100:.2f}"

# ───────── Cards & values ───────
RANKS = ["A","2","3","4","5","6","7","8","9","10","J","Q","K"]
SUITS = ["♠","♥","♦","♣"]
RED = {"♥","♦"}
RANK_ORDER = {"A":14,"K":13,"Q":12,"J":11,"10":10,"9":9,"8":8,"7":7,"6":6,"5":5,"4":4,"3":3,"2":2}

def card_value(rank: str) -> int:
    """Return blackjack value for a rank (Ace high = 11 here; soft logic handled in hand_value)."""
    if rank in {"10","J","Q","K"}:
        return 10
    if rank == "A":
        return 11
    return int(rank)

def hand_value(cards) -> int:
    """Return best blackjack total (aces can drop from 11 to 1 as needed)."""
    total = 0
    aces = 0
    for r, _ in cards:
        total += card_value(r)
        if r == "A":
            aces += 1
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total

def hand_value_display(cards) -> str:
    """Return display string for hand value (e.g., '10/20' for soft hands, '21' when it's 21, '2/12' for A+A)."""
    if not cards:
        return "0"
    
    # Count aces and calculate totals
    aces = sum(1 for r, _ in cards if r == "A")
    
    # Hard total (all aces count as 1)
    hard_total = sum(1 if r == "A" else (10 if r in {"10","J","Q","K"} else int(r)) for r, _ in cards)
    
    # If no aces, just return hard total
    if aces == 0:
        return str(hard_total)
    
    # Soft total (one ace counts as 11, rest as 1)
    soft_total = hard_total + 10
    
    # If soft total is over 21, only hard total makes sense
    if soft_total > 21:
        return str(hard_total)
    
    # If soft total is exactly 21, show only "21"
    if soft_total == 21:
        return "21"
    
    # Soft total is < 21, show "hard/soft"
    return f"{hard_total}/{soft_total}"

def is_blackjack(cards) -> bool:
    """Return True if a 2-card natural 21."""
    return len(cards) == 2 and hand_value(cards) == 21

# ───────── Shoe (6 decks) ───────
class Shoe:
    """Simple shoe of N decks, reshuffles automatically when empty."""
    def __init__(self, decks=6):
        self.decks = decks
        self.cards = [(r,s) for _ in range(decks) for r in RANKS for s in SUITS]
        random.shuffle(self.cards)
    def deal(self):
        if not self.cards:
            self.__init__(self.decks)
        return self.cards.pop()

# ───────── Hand state ─────────
@dataclass
class Hand:
    """Player hand state including main bet and side bets."""
    cards: list = field(default_factory=list)
    bet: int = 0
    doubled: bool = False
    stood: bool = False
    done: bool = False
    split_aces: bool = False  # when splitting aces: one-card rule applies
    pp_bet: int = 0           # Perfect Pairs side bet
    t213_bet: int = 0         # 21+3 side bet

# ───────── App state ─────────
def init_state():
    """Initialize all Streamlit session_state keys."""
    st.session_state.shoe = Shoe()
    st.session_state.bankroll = None
    st.session_state.cash_in = 0

    st.session_state.in_hand = False
    st.session_state.phase = "idle"  # idle | player | dealer | settle

    st.session_state.hands = []
    st.session_state.cur = 0
    st.session_state.dealer = []

    # Fixed split limit like real tables
    st.session_state.split_limit = 4
    st.session_state.split_happened = False

    # Insurance / Even Money
    st.session_state.offered_insurance = False
    st.session_state.insurance = 0
    st.session_state.insurance_active = False
    st.session_state.peek_done = False
    st.session_state.even_money_offered = False
    st.session_state.even_money_decided = False

    # Main stats (counters)
    st.session_state.stats = {"played":0,"won":0,"lost":0,"push":0}
    st.session_state.side_stats = {
        "pp":{"bets":0,"stake":0,"payout_return":0,"wins":{"perfect":0,"colored":0,"mixed":0}},
        "t213":{"bets":0,"stake":0,"payout_return":0,"wins":{"straight_flush":0,"three_kind":0,"straight":0,"flush":0}},
    }

    # Flash messages & outcomes per round
    st.session_state.flash = []          # messages queued when round ends
    st.session_state.last_outcomes = []  # outcomes for the current round only

    # One-time welcome
    st.session_state.first_welcome_shown = False

    # Persistent hand history across rounds
    st.session_state.history = []        # list[dict] — every settled hand appended here

    # Animated chip state
    st.session_state.chip = {"show": False, "amount": 0, "where": "center", "direction": "none"}

if "shoe" not in st.session_state:
    init_state()

# ───────── Casino-style message helpers ─────────
MSG_EMOJI = {
    "welcome": "🎰",
    "info": "ℹ️",
    "hint": "💡",
    "win": "💰",
    "lose": "❌",
    "push": "🟰",
    "bj": "🖤🃏",
    "insurance": "🛡️",
    "even": "💵",
    "cashout": "🏁",
    "warning": "⚠️",
    "chip": "🎟️",
}

def add_msg(kind: str, text: str):
    """Queue a flash message of a given kind."""
    prefix = MSG_EMOJI.get(kind, "")
    st.session_state.flash.append(f"{prefix} {text}" if prefix else text)

# ───────── Chip animation helpers ─────────
def chip_set(amount_cents: int, where: str = "center", direction: str = "none"):
    """Set chip display with animation target."""
    st.session_state.chip.update({"show": True, "amount": amount_cents, "where": where, "direction": direction})

def chip_css_transform(where: str) -> tuple[int,int]:
    """Return (x, y) offset for chip position."""
    if where == "dealer_left":   return (-300, -100)  # loss - toward dealer
    if where == "player_right":  return (300, -100)   # win - toward player
    return (0, -10)                                   # center (start & push)

# ───────── Side-bet helpers ─────────
PP_PAYOUTS = {"perfect":25,"colored":12,"mixed":6}
T213_PAYOUTS = {"straight_flush":40,"three_kind":30,"straight":10,"flush":5}

def pp_kind(c1, c2):
    """Classify Perfect Pairs type for two player cards."""
    r1,s1=c1; r2,s2=c2
    if r1 != r2:
        return None
    if s1 == s2:
        return "perfect"
    red1 = s1 in RED
    red2 = s2 in RED
    if (red1 and red2) or ((not red1) and (not red2)):
        return "colored"
    return "mixed"

def is_flush(cards): return len({s for _,s in cards}) == 1
def is_trips(cards): return len({r for r,_ in cards}) == 1
def is_straight3(cards):
    """Return True if 3-card straight (A can be low)."""
    vals = sorted([RANK_ORDER[r] for r,_ in cards])
    def consec(a): return a[0]+1==a[1] and a[1]+1==a[2]
    if consec(vals):
        return True
    vals_low = [1 if v==14 else v for v in vals]
    vals_low.sort()
    return consec(vals_low)

def eval_21p3(p_cards, dealer_up):
    """Evaluate 21+3 on player's two cards + dealer upcard."""
    trio=[p_cards[0], p_cards[1], dealer_up]
    if is_flush(trio) and is_straight3(trio): return "straight_flush"
    if is_trips(trio): return "three_kind"
    if is_straight3(trio): return "straight"
    if is_flush(trio): return "flush"
    return None

# ───────── Paytable / Rules / Info helpers ─────────
def render_rules():
    """Render game rules."""
    st.markdown("""
### 🎲 How to Play Blackjack

**Objective:** Get a hand value closer to 21 than the dealer without going over.

**Card Values:**
- Number cards (2-10): Face value
- Face cards (J, Q, K): 10 points
- Aces: 1 or 11 (whichever is better)

**Game Flow:**
1. **Place your bet** - Choose your main bet and optional side bets
2. **Cards are dealt** - You and dealer each get 2 cards (dealer's second card is face down)
3. **Your turn** - Choose to:
   - **Hit**: Take another card
   - **Stand**: Keep your current hand
   - **Double**: Double your bet, take one card, and stand (only on 9-11)
   - **Split**: Split matching cards into two hands (costs another bet)
4. **Dealer's turn** - Dealer hits until reaching 17 or higher
5. **Winner determined** - Closest to 21 wins!

**Special Rules:**
- **Blackjack** (Ace + 10-value card): Pays 3:2
- **Bust** (over 21): Automatic loss
- **Push** (tie): Bet returned
- **Insurance**: When dealer shows Ace, you can bet up to half your bet that dealer has Blackjack (pays 2:1)
- **Even Money**: If you have Blackjack and dealer shows Ace, you can take 1:1 payout immediately

**Side Bets:**
- **Perfect Pairs**: Win if your first two cards are a pair (25:1 for perfect match)
- **21+3**: Win if your two cards + dealer's upcard form a poker hand (40:1 for straight flush)
""")

def sidebets_paytable():
    """Render side-bets paytable inside a popover."""
    st.markdown("#### 21+3 — Paytable")
    st.markdown("""
| Combination       | Pays |
|-------------------|------|
| Straight Flush    | **40 : 1** |
| Three of a Kind   | **30 : 1** |
| Straight          | **10 : 1** |
| Flush             | **5 : 1** |
""")
    st.markdown("#### Perfect Pairs — Paytable")
    st.markdown("""
| Pair Type            | Pays |
|----------------------|------|
| Perfect (same suit)  | **25 : 1** |
| Colored (same color) | **12 : 1** |
| Mixed                | **6 : 1** |
""")
    st.caption("Note: payouts are to-one (e.g., $10 at 5:1 returns $60: $50 profit + $10 stake).")

# ───────── History helpers ─────────
def cards_str(cards) -> str:
    """Return a compact string like 'A♠, 9♦' for a list of (rank, suit)."""
    return ", ".join([f"{r}{s}" for r,s in cards])

def log_history(result: str, hand: Hand, payout: int, player_val: int, dealer_val: int):
    """Append a single settled hand to the persistent history."""
    net = payout - hand.bet if result == "win" else (0 if result == "push" else -hand.bet)
    st.session_state.history.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "result": result,                      # "win" | "lose" | "push"
        "player_value": player_val,
        "dealer_value": dealer_val,
        "bet": hand.bet,
        "payout": payout,
        "net": net,
        "player_cards": cards_str(hand.cards),
        "dealer_cards": cards_str(st.session_state.dealer),
    })

def render_history_popover():
    """Render the hand history with summary percentages and ROI."""
    hist = st.session_state.history
    if not hist:
        st.write("No hands recorded yet.")
        return

    # Summary stats
    played = len(hist)
    wins = sum(1 for h in hist if h["result"]=="win")
    losses = sum(1 for h in hist if h["result"]=="lose")
    pushes = played - wins - losses

    total_bet = sum(h["bet"] for h in hist)
    total_payout = sum(h["payout"] for h in hist)
    net = total_payout - total_bet
    roi = (net / total_bet * 100.0) if total_bet > 0 else 0.0

    st.markdown(f"**Hands:** {played} • **Win:** {wins} ({wins/played*100:.1f}%) • "
                f"**Loss:** {losses} ({losses/played*100:.1f}%) • "
                f"**Push:** {pushes} ({pushes/played*100:.1f}%)")
    st.markdown(f"**Total Bet:** {fmt(total_bet)} • **Total Return:** {fmt(total_payout)} • "
                f"**Net:** {fmt(net)} • **ROI:** {roi:.2f}%")

    st.dataframe(
        [{ "#": i+1,
           "Time": h["time"],
           "Result": h["result"],
           "Player": h["player_value"],
           "Dealer": h["dealer_value"],
           "Bet": fmt(h["bet"]),
           "Payout": fmt(h["payout"]),
           "Net": fmt(h["net"]),
           "Player cards": h["player_cards"],
           "Dealer cards": h["dealer_cards"],
        } for i, h in enumerate(hist)],
        use_container_width=True,
        hide_index=True,
    )

# ───────── UI base + cards CSS/renderers ─────────
st.set_page_config(page_title="Blackjack", page_icon="🃏", layout="centered")
st.title("🃏 Blackjack — Streamlit (Single Player)")

st.markdown("""
<style>
/* Casino felt background */
.stApp {
  background: radial-gradient(80% 60% at 50% 30%, #115e3b 0%, #0e4e32 35%, #0b3f28 70%, #082a1c 100%);
}

/* Cards */
.cardrow { display:flex; gap:12px; flex-wrap:wrap; align-items:center; }
.card { width:64px; height:88px; border-radius:10px; border:2px solid #e5e7eb;
  background: linear-gradient(180deg,#ffffff 0%, #fafafa 100%);
  box-shadow: 0 6px 16px rgba(0,0,0,0.28);
  position:relative; display:flex; align-items:center; justify-content:center;
  font-family: system-ui, -apple-system, Segoe UI, Roboto, 'Noto Color Emoji'; color:#111827; }
.rank { position:absolute; top:4px; left:6px; font-weight:700; font-size:14px; }
.rank.bottom { top:auto; bottom:4px; left:auto; right:6px; transform: rotate(180deg); }
.pip { font-size:28px; line-height:1; }
.red { color:#ef4444; } .black { color:#111827; }

/* Red back for hidden cards */
.card.back {
  background: repeating-linear-gradient(45deg,#b91c1c 0 6px,#991b1b 6px 12px);
  border-color:#7f1d1d;
}

/* Dealer row with a stacked deck on the left */
.dealerrow { display:flex; align-items:center; gap:18px; }
.deck-stack { position:relative; width:68px; height:92px; }
.deck-card {
  width:68px; height:92px; border-radius:10px; border:2px solid #7f1d1d;
  background: repeating-linear-gradient(45deg,#b91c1c 0 6px,#991b1b 6px 12px);
  box-shadow: 0 6px 16px rgba(0,0,0,0.28);
  position:absolute; top:0; left:0;
}
.deck-card:nth-child(1) { transform: translate(0px, 0px) rotate(-1deg); }
.deck-card:nth-child(2) { transform: translate(4px, 3px) rotate(0.6deg); }
.deck-card:nth-child(3) { transform: translate(8px, 6px) rotate(-0.2deg); }
.deck-card:nth-child(4) { transform: translate(12px, 9px) rotate(0.8deg); }

/* Animated chip */
.chip { 
  position:absolute; width: 50px; height: 50px; border-radius:50%;
  background: radial-gradient(circle at 30% 30%, #a78bfa, #5b21b6);
  color:#fff; font-weight:800; font-size:12px; 
  display:flex; align-items:center; justify-content:center;
  border:3px solid #e2e8f0; box-shadow:0 10px 20px rgba(0,0,0,.35);
  z-index:50; 
  transform: translate(var(--tx,0px), var(--ty,0px)); 
  transition: transform 650ms cubic-bezier(.2,.8,.2,1); 
}
#chip-center-anchor { position: relative; height: 0; }

/* Inline chip variant */
.chip-inline {
  display:inline-flex; align-items:center; justify-content:center;
  width: 40px; height: 40px; border-radius:50%;
  background: radial-gradient(circle at 30% 30%, #a78bfa, #5b21b6);
  color:#fff; font-weight:800; font-size: 12px;
  border:2px solid #e2e8f0; box-shadow:0 6px 12px rgba(0,0,0,.28);
}

/* Header container to place chip right next to the name */
.hdr { display: flex; align-items: center; gap: 10px; margin: 0 0 6px 0; }
.hdr h2 { margin: 0; }

/* Make small captions readable on green felt */
.block-container .stCaption { color:#e5e7eb !important; }

/* Larger popover buttons */
details > summary {
  padding: 14px 20px !important;
  white-space: nowrap !important;
  font-size: 18px !important;
  font-weight: 700 !important;
  min-width: 200px !important;
}

/* Give captions breathing room */
div[data-testid="stCaptionContainer"] { margin-top: 12px !important; }

/* Ensure chip stays on top */
.chip { z-index: 200 !important; }
</style>
""", unsafe_allow_html=True)

def suit_cls(s): return "red" if s in RED else "black"

def card_html(rank, suit, hidden=False):
    """Return HTML for a card; 'hidden' renders a red back."""
    if hidden:
        return '<div class="card back"></div>'
    return f'''<div class="card">
      <div class="rank {suit_cls(suit)}">{rank}<span>{suit}</span></div>
      <div class="pip {suit_cls(suit)}">{suit}</div>
      <div class="rank bottom {suit_cls(suit)}">{rank}<span>{suit}</span></div>
    </div>'''

def render_hand(cards, hide_hole=False):
    """Return HTML row of cards; 'hide_hole' hides dealer's second card."""
    out=[]
    for i,(r,s) in enumerate(cards):
        out.append(card_html(r, s, hidden=(hide_hole and i==1)))
    return '<div class="cardrow">' + ''.join(out) + '</div>'

# Extra: deck stack + dealer area
def deck_html(stack_size: int = 4) -> str:
    """Small stacked deck visual next to dealer area."""
    cards = ''.join('<div class="deck-card"></div>' for _ in range(stack_size))
    return f'<div class="deck-stack">{cards}</div>'

def render_dealer_area(hide_hole: bool = True) -> str:
    """Dealer area: stacked deck + dealer hand."""
    hand = render_hand(st.session_state.dealer, hide_hole=hide_hole)
    return '<div class="dealerrow">' + deck_html() + hand + '</div>'

# ───────── Round flow ─────────
def start_round(main:int, pp:int, t213:int):
    """Begin a new player round if bankroll covers all stakes."""
    total = main + pp + t213
    if st.session_state.bankroll is None or st.session_state.bankroll < total:
        st.error("Insufficient bankroll.")
        return

    st.session_state.bankroll -= total

    # side bet stake tracking
    if pp > 0:
        st.session_state.side_stats["pp"]["bets"] += 1
        st.session_state.side_stats["pp"]["stake"] += pp
    if t213 > 0:
        st.session_state.side_stats["t213"]["bets"] += 1
        st.session_state.side_stats["t213"]["stake"] += t213

    # init hand
    st.session_state.hands = [Hand(cards=[], bet=main, pp_bet=pp, t213_bet=t213)]
    st.session_state.cur = 0
    st.session_state.dealer = []
    st.session_state.in_hand = True
    st.session_state.phase = "player"
    st.session_state.split_happened = False

    st.session_state.offered_insurance = False
    st.session_state.insurance = 0
    st.session_state.insurance_active = False
    st.session_state.peek_done = False
    st.session_state.even_money_offered = False
    st.session_state.even_money_decided = False

    # reset outcomes (this round only)
    st.session_state.last_outcomes = []

    d = st.session_state.shoe
    st.session_state.hands[0].cards.append(d.deal())
    st.session_state.dealer.append(d.deal())   # upcard
    st.session_state.hands[0].cards.append(d.deal())
    st.session_state.dealer.append(d.deal())   # hole

    # Start chip in the CENTER
    chip_set(st.session_state.hands[0].bet, where="center", direction="none")

    evaluate_sidebets()

    # Natural BJ instant payout if dealer does NOT show Ace or Ten-value
    up_r, _ = st.session_state.dealer[0]
    if is_blackjack(st.session_state.hands[0].cards):
        if up_r in {"A","10","J","Q","K"}:
            if up_r == "A":
                st.session_state.offered_insurance = True
                st.session_state.even_money_offered = True
                st.session_state.even_money_decided = False
            else:
                st.session_state.peek_done = True
                if is_blackjack(st.session_state.dealer):
                    resolve_dealer_blackjack()
                    end_round()
                    st.session_state.phase = "idle"
        else:
            pay = int(round(st.session_state.hands[0].bet * 2.5))
            st.session_state.bankroll += pay
            st.session_state.stats["won"] += 1
            # Log history now because the round ends immediately
            h = st.session_state.hands[0]
            log_history("win", h, pay, hand_value(h.cards), hand_value(st.session_state.dealer))
            chip_set(pay, where="player_right", direction="right")
            add_msg("bj", f"🎉🤑 Blackjack! Paid 3:2 → {fmt(pay)}. Beautiful hand!")
            end_round()
            st.session_state.phase = "idle"

def evaluate_sidebets():
    """Evaluate side-bets right after the initial deal."""
    h = st.session_state.hands[0]
    up = st.session_state.dealer[0]
    # Perfect Pairs
    if h.pp_bet > 0:
        kind = pp_kind(h.cards[0], h.cards[1])
        if kind:
            mult = PP_PAYOUTS[kind]
            gain = h.pp_bet * (mult + 1)  # include stake back
            st.session_state.bankroll += gain
            st.session_state.side_stats["pp"]["payout_return"] += gain
            st.session_state.side_stats["pp"]["wins"][kind] += 1
            add_msg("chip", f"Perfect Pairs ({kind}) paid {mult}:1 → {fmt(gain)}")
    # 21+3
    if h.t213_bet > 0:
        res = eval_21p3(h.cards, up)
        if res:
            mult = T213_PAYOUTS[res]
            gain = h.t213_bet * (mult + 1)
            st.session_state.bankroll += gain
            st.session_state.side_stats["t213"]["payout_return"] += gain
            st.session_state.side_stats["t213"]["wins"][res] += 1
            add_msg("chip", f"21+3 ({res}) paid {mult}:1 → {fmt(gain)}")

def dealer_play():
    """Dealer hits until hard/soft 17 (S17)."""
    while hand_value(st.session_state.dealer) < 17:
        st.session_state.dealer.append(st.session_state.shoe.deal())

def settle(h: Hand):
    """Settle a single player hand vs the final dealer hand and log history."""
    pv = hand_value(h.cards)
    dv = hand_value(st.session_state.dealer)

    if pv > 21:
        st.session_state.stats["lost"] += 1
        st.session_state.last_outcomes.append({"result":"lose","pv":pv,"dv":dv,"payout":0})
        log_history("lose", h, 0, pv, dv)
        chip_set(h.bet, where="dealer_left", direction="left")
        add_msg("", f"❌💸 You bust ({pv}). Dealer {dv}. Better luck next hand!")
        return

    # Natural Blackjack 3:2 (not after split)
    if is_blackjack(h.cards) and not st.session_state.split_happened:
        pay = int(round(h.bet * 2.5))
        st.session_state.bankroll += pay
        st.session_state.stats["won"] += 1
        st.session_state.last_outcomes.append({"result":"win","pv":pv,"dv":dv,"payout":pay})
        log_history("win", h, pay, pv, dv)
        chip_set(pay, where="player_right", direction="right")
        add_msg("bj", f"🎉🤑 Blackjack! Paid 3:2 → {fmt(pay)}. Beautiful hand!")
        return

    if dv > 21:
        pay = h.bet * 2
        st.session_state.bankroll += pay
        st.session_state.stats["won"] += 1
        st.session_state.last_outcomes.append({"result":"win","pv":pv,"dv":dv,"payout":pay})
        log_history("win", h, pay, pv, dv)
        chip_set(pay, where="player_right", direction="right")
        add_msg("", f"💸🤑 Dealer busts ({dv}). You win with {pv}! Paid {fmt(pay)}.")
    elif pv > dv:
        pay = h.bet * 2
        st.session_state.bankroll += pay
        st.session_state.stats["won"] += 1
        st.session_state.last_outcomes.append({"result":"win","pv":pv,"dv":dv,"payout":pay})
        log_history("win", h, pay, pv, dv)
        chip_set(pay, where="player_right", direction="right")
        add_msg("win", f"🤑 You win {pv} vs dealer {dv}. Paid {fmt(pay)}. Nice one!")
    elif pv == dv:
        pay = h.bet
        st.session_state.bankroll += pay
        st.session_state.stats["push"] += 1
        st.session_state.last_outcomes.append({"result":"push","pv":pv,"dv":dv,"payout":pay})
        log_history("push", h, pay, pv, dv)
        chip_set(h.bet, where="center", direction="none")
        add_msg("push", f"😬 Push {pv} vs {dv}. Bet returned {fmt(pay)}.")
    else:
        st.session_state.stats["lost"] += 1
        st.session_state.last_outcomes.append({"result":"lose","pv":pv,"dv":dv,"payout":0})
        log_history("lose", h, 0, pv, dv)
        chip_set(h.bet, where="dealer_left", direction="left")
        add_msg("", f"❌😞 Dealer wins {dv} vs your {pv}. Tough one—try again?")

def resolve_dealer_blackjack():
    """Handle dealer natural blackjack (insurance and even-money already handled)."""
    if st.session_state.insurance > 0:
        st.session_state.bankroll += st.session_state.insurance * 3  # stake back + 2:1
        add_msg("insurance", f"Insurance paid 2:1 → {fmt(st.session_state.insurance*3)}")
    h = st.session_state.hands[0]
    pv = hand_value(h.cards)
    dv = hand_value(st.session_state.dealer)
    if is_blackjack(h.cards):
        st.session_state.bankroll += h.bet  # push
        st.session_state.stats["push"] += 1
        log_history("push", h, h.bet, pv, dv)
        chip_set(h.bet, where="center", direction="none")
        add_msg("push", f"😬 Dealer Blackjack. Push. Returned {fmt(h.bet)}.")
    else:
        st.session_state.stats["lost"] += 1
        log_history("lose", h, 0, pv, dv)
        chip_set(h.bet, where="dealer_left", direction="left")
        add_msg("lose", "❌ Dealer Blackjack. Hand is over.")

def end_round():
    """Close the round and reset in-hand flags."""
    st.session_state.in_hand = False
    st.session_state.stats["played"] += 1
    st.session_state.insurance_active = False

def next_or_dealer():
    """Advance to next playable player hand, otherwise to dealer phase."""
    for i, h in enumerate(st.session_state.hands):
        if not h.done and not h.stood and hand_value(h.cards) <= 21:
            st.session_state.cur = i
            st.session_state.phase = "player"
            return
    st.session_state.phase = "dealer"

# ───────── Player actions (no st.rerun inside callbacks) ─────────
def act_hit():
    """Player takes one card."""
    h = st.session_state.hands[st.session_state.cur]
    if h.done or h.stood or h.split_aces:
        return
    h.cards.append(st.session_state.shoe.deal())
    v = hand_value(h.cards)
    if v >= 21:
        h.done = True
        h.stood = (v == 21)  # auto-stand on 21
        next_or_dealer()

def act_stand():
    """Player stands."""
    h = st.session_state.hands[st.session_state.cur]
    h.stood = True
    h.done = True
    next_or_dealer()

def act_double():
    """Player doubles: double bet, take one, auto-stand."""
    h = st.session_state.hands[st.session_state.cur]
    v = hand_value(h.cards)
    ok = (len(h.cards)==2 and 9<=v<=11 and not h.doubled and not h.stood and not h.done and not h.split_aces)
    if not ok:
        return
    if st.session_state.bankroll < h.bet:
        return
    st.session_state.bankroll -= h.bet
    h.bet *= 2
    h.doubled = True
    h.cards.append(st.session_state.shoe.deal())
    h.done = True
    next_or_dealer()

def can_split(h: Hand) -> bool:
    """Return True if the current hand can be split."""
    if len(h.cards) != 2 or h.done or h.stood:
        return False
    (r1,_), (r2,_) = h.cards
    if r1 != r2:
        return False
    return len(st.session_state.hands) < st.session_state.split_limit

def act_split():
    """Split equal ranks into two hands (aces receive one card each, then stand)."""
    h = st.session_state.hands[st.session_state.cur]
    if not can_split(h):
        return
    if st.session_state.bankroll < h.bet:
        return
    st.session_state.bankroll -= h.bet
    c1, c2 = h.cards[0], h.cards[1]
    is_aces = (c1[0] == "A" and c2[0] == "A")
    h.cards = [c1]
    h.split_aces = is_aces
    new_hand = Hand(cards=[c2], bet=h.bet, split_aces=is_aces)
    st.session_state.hands.insert(st.session_state.cur + 1, new_hand)
    h.cards.append(st.session_state.shoe.deal())
    new_hand.cards.append(st.session_state.shoe.deal())
    st.session_state.split_happened = True
    if is_aces:
        h.stood = True; h.done = True
        new_hand.stood = True; new_hand.done = True
    next_or_dealer()

# ───────── Insurance / Even Money ─────────
def take_insurance():
    """Take half-bet insurance when dealer shows an Ace."""
    if st.session_state.insurance > 0:
        return
    h = st.session_state.hands[0]
    max_ins = h.bet // 2
    if max_ins <= 0 or st.session_state.bankroll < max_ins:
        return
    st.session_state.bankroll -= max_ins
    st.session_state.insurance = max_ins
    st.session_state.insurance_active = True
    add_msg("insurance", f"Insurance taken: {fmt(max_ins)}")

def take_even_money():
    """Take even money (1:1) when you have a natural BJ vs dealer Ace."""
    h = st.session_state.hands[0]
    st.session_state.bankroll += h.bet * 2  # 1:1
    st.session_state.stats["won"] += 1
    st.session_state.even_money_decided = True
    # Log win and close round immediately
    log_history("win", h, h.bet * 2, hand_value(h.cards), hand_value(st.session_state.dealer))
    chip_set(h.bet * 2, where="player_right", direction="right")
    add_msg("even", "Even Money selected: paid 1:1. Round closed.")
    end_round()
    st.session_state.phase = "idle"

def decline_even_money():
    """Decline even money; dealer will peek now."""
    st.session_state.even_money_decided = True
    st.session_state.peek_done = True
    if is_blackjack(st.session_state.dealer):
        resolve_dealer_blackjack()
        end_round()
        st.session_state.phase = "idle"

# ───────── Sidebar ─────────
with st.sidebar:
    st.header("Bankroll & Controls")
    if st.session_state.bankroll is None:
        dep = st.number_input("Initial deposit ($)", min_value=1.0, step=1.0, value=50.0)
        if st.button("📥 Deposit"):
            cents = to_cents(dep)
            st.session_state.bankroll = cents
            st.session_state.cash_in = cents
            st.rerun()
    else:
        st.metric("Bankroll", fmt(st.session_state.bankroll))
        addv = st.number_input("Add funds ($)", min_value=0.0, step=1.0, value=0.0, key="add")
        if st.button("➕ Add"):
            c = to_cents(addv)
            st.session_state.bankroll += c
            st.session_state.cash_in += c
            st.rerun()

        # Cash out with simple end-of-session messages
        if st.button("🏁 Cash out (end)"):
            bankroll = st.session_state.bankroll or 0
            buyin = st.session_state.cash_in or 0
            profit = bankroll - buyin

            if profit > 0:
                msg1 = f"🎉 Congrats! You finished UP {fmt(profit)}."
            elif profit < 0:
                msg1 = f"😭 You finished DOWN {fmt(-profit)}. Better luck next time!"
            else:
                msg1 = "😬 You finished EVEN. Not bad!"

            msg2 = "🎰 See you soon at the Nova Casino! 🍀"

            st.session_state.post_cashout_msgs = [("cashout", msg1), ("info", msg2)]
            init_state()
            st.rerun()

# ───────── Require deposit (first screen) ─────────
if st.session_state.bankroll is None:
    # Show any post-cashout messages once, then clear them
    if "post_cashout_msgs" in st.session_state:
        for _, text in st.session_state.post_cashout_msgs:
            st.info(text)
        del st.session_state.post_cashout_msgs

    st.info("Make an initial deposit in the sidebar to start.")
    st.stop()

# ───────── Top controls (Rules, History & Paytable) ─────────
hdr_l, hdr_r1, hdr_r2, hdr_r3 = st.columns([1, 0.32, 0.32, 0.32])
with hdr_r1:
    with st.popover("📖 Rules", use_container_width=True):
        render_rules()
with hdr_r2:
    with st.popover("🧾 History", use_container_width=True):
        render_history_popover()
with hdr_r3:
    with st.popover("ℹ️ Paytable", use_container_width=True):
        sidebets_paytable()

# ───────── Table layout ─────────
col1, col2 = st.columns(2)
with col1:
    # Dealer header with chip (when dealer wins)
    st.markdown(
        f'<div class="hdr"><h2>Dealer</h2>' + 
        (f'<span class="chip-inline">{fmt(st.session_state.chip["amount"])}</span>'
         if (st.session_state.chip.get("show") and st.session_state.chip.get("where") == "dealer_left" and not st.session_state.in_hand)
         else '') + 
        '</div>', unsafe_allow_html=True
    )

    if st.session_state.dealer:
        reveal = (st.session_state.phase in ("dealer","settle")) or st.session_state.peek_done or not st.session_state.in_hand
        st.markdown(render_dealer_area(hide_hole=not reveal), unsafe_allow_html=True)
        if st.session_state.in_hand and st.session_state.insurance_active and not reveal:
            st.caption(f"🛡️ Insurance active: {fmt(st.session_state.insurance)}")
        if reveal:
            st.caption(f"Value: {hand_value_display(st.session_state.dealer)}")
    else:
        st.caption("Waiting for deal…")

with col2:
    # Player header with chip (when player wins)
    st.markdown(
        f'<div class="hdr"><h2>Player</h2>' + 
        (f'<span class="chip-inline">{fmt(st.session_state.chip["amount"])}</span>'
         if (st.session_state.chip.get("show") and st.session_state.chip.get("where") == "player_right" and not st.session_state.in_hand)
         else '') + 
        '</div>', unsafe_allow_html=True
    )

    if st.session_state.hands:
        for i, h in enumerate(st.session_state.hands):
            cur = " (current)" if (st.session_state.in_hand and st.session_state.phase=="player" and i == st.session_state.cur) else ""
            st.markdown(f"**Hand {i+1}{cur} — Bet: {fmt(h.bet)}**")
            st.markdown(render_hand(h.cards), unsafe_allow_html=True)
            st.caption(f"Value: {hand_value_display(h.cards)}")
    else:
        st.caption("No hand in progress.")

# Render animated chip
if st.session_state.chip.get("show"):
    tx, ty = chip_css_transform(st.session_state.chip.get("where", "center"))
    st.markdown(f'<div id="chip-center-anchor"></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="chip" style="--tx:{tx}px; --ty:{ty}px;">{fmt(st.session_state.chip["amount"])}</div>',
        unsafe_allow_html=True
    )

st.divider()

# ───────── Phase engine (after render) ─────────
if st.session_state.in_hand:
    if st.session_state.phase == "dealer":
        st.session_state.peek_done = True
        dealer_play()
        st.session_state.phase = "settle"
        st.rerun()

    if st.session_state.phase == "settle":
        for h in st.session_state.hands:
            settle(h)
        end_round()
        st.session_state.phase = "idle"
        st.rerun()

# ───────── Pre-deal / In-hand UI ─────────
if not st.session_state.in_hand:
    # Welcome message only once, on the initial screen before the first deal
    if not st.session_state.first_welcome_shown:
        add_msg("", "🎰🎰🎰 Welcome to the Nova Casino! Place your bet and good luck! 🍀")
        st.session_state.first_welcome_shown = True

    st.subheader("Place your bets")

    c1, c2, c3 = st.columns(3)
    with c1:
        main_b = to_cents(st.number_input("Main bet ($)", min_value=0.0, step=1.0, value=10.0, key="main_b"))
    with c2:
        pp_b = to_cents(st.number_input("Perfect Pairs ($)", min_value=0.0, step=1.0, value=0.0, key="pp_b"))
    with c3:
        t213_b = to_cents(st.number_input("21+3 ($)", min_value=0.0, step=1.0, value=0.0, key="t213_b"))

    total_stake = main_b + pp_b + t213_b
    st.caption(f"Total stake if dealt now: {fmt(total_stake)}")
    if total_stake > st.session_state.bankroll:
        st.warning(f"⚠️ Not enough bankroll for {fmt(total_stake)}. Add funds or reduce stake.")

    if st.button("🎲 Deal"):
        start_round(main_b, pp_b, t213_b)
        st.rerun()
else:
    # Even Money if player has BJ and dealer shows Ace
    h0 = st.session_state.hands[0]
    if (is_blackjack(h0.cards) and not st.session_state.even_money_decided and
        st.session_state.dealer and st.session_state.dealer[0][0] == "A" and st.session_state.phase == "player"):
        em1, em2 = st.columns(2)
        with em1:
            st.button("✅ Even Money (1:1)", on_click=take_even_money, help="Instant 1:1 payout for your Blackjack; round closes.")
        with em2:
            st.button("❌ Play normally", on_click=decline_even_money, help="No Even Money; dealer will peek now.")
        st.caption("You have Blackjack and the dealer shows an Ace. Take 1:1 now or play normally.")
        st.stop()

    # Insurance when dealer shows Ace (if Even Money not taken)
    if (st.session_state.dealer and st.session_state.dealer[0][0] == "A"
        and not st.session_state.peek_done
        and not (is_blackjack(h0.cards) and not st.session_state.even_money_decided)
        and st.session_state.phase == "player"):
        ic1, ic2 = st.columns(2)
        with ic1:
            st.button("🛡️ Take Insurance (½ bet)", on_click=take_insurance,
                      help="Costs half of your main bet; pays 2:1 only if dealer has Blackjack.")
        with ic2:
            if st.button("Peek & continue", help="Dealer checks the hole card now; hand ends immediately if dealer has Blackjack."):
                st.session_state.peek_done = True
                if is_blackjack(st.session_state.dealer):
                    resolve_dealer_blackjack()
                    end_round()
                    st.session_state.phase = "idle"
                st.rerun()

    # Player action buttons
    h = st.session_state.hands[st.session_state.cur]
    v = hand_value(h.cards)
    can_hit = (st.session_state.phase=="player" and not h.done and not h.stood and not h.split_aces and v < 21)
    can_stand = (st.session_state.phase=="player" and not h.done and not h.stood)
    can_double = (st.session_state.phase=="player" and len(h.cards)==2 and 9<=v<=11 and not h.doubled and not h.stood and not h.done and not h.split_aces
                  and st.session_state.bankroll >= h.bet)
    can_split_now = (st.session_state.phase=="player" and can_split(h) and st.session_state.bankroll >= h.bet)

    b1,b2,b3,b4 = st.columns(4)
    with b1:
        st.button("Hit", disabled=not can_hit, on_click=act_hit, help="Take one more card.")
    with b2:
        st.button("Stand", disabled=not can_stand, on_click=act_stand, help="End your turn for this hand.")
    with b3:
        st.button("Double", disabled=not can_double, on_click=act_double, help="Double your bet, take one card, and stand.")
    with b4:
        st.button("Split", disabled=not can_split_now, on_click=act_split, help="Split equal ranks into two hands (Aces: one card each).")

# ───────── Flash messages & Stats ─────────
if not st.session_state.in_hand and st.session_state.flash:
    for msg in st.session_state.flash:
        low = msg.lower()
        if any(k in low for k in ["you win", "paid", "blackjack", "dealer busts"]):
            st.success(msg)
        elif any(k in low for k in ["push", "returned", "even money", "insurance", "welcome", "side bets", "cash out"]):
            st.info(msg)
        elif any(k in low for k in ["❌", "warning", "you bust", "dealer blackjack. hand is over"]):
            st.warning(msg)
        else:
            st.info(msg)
    st.session_state.flash = []

if not st.session_state.in_hand:
    st.info(f"Bankroll: {fmt(st.session_state.bankroll)}")
    s = st.session_state.stats
    st.caption(f"Hands: {s['played']} • Won: {s['won']} • Lost: {s['lost']} • Push: {s['push']}")
    ss = st.session_state.side_stats
    pp_net = ss['pp']['payout_return'] - ss['pp']['stake']
    t213_net = ss['t213']['payout_return'] - ss['t213']['stake']
    with st.expander("📊 Side-bet stats"):
        st.markdown("**Perfect Pairs**")
        st.write(f"Bets: {ss['pp']['bets']} | Stake: {fmt(ss['pp']['stake'])} | Return: {fmt(ss['pp']['payout_return'])} | Net: {fmt(pp_net)}")
        st.write(f"Wins: Perfect={ss['pp']['wins']['perfect']} • Colored={ss['pp']['wins']['colored']} • Mixed={ss['pp']['wins']['mixed']}")
        st.markdown("**21+3**")
        st.write(f"Bets: {ss['t213']['bets']} | Stake: {fmt(ss['t213']['stake'])} | Return: {fmt(ss['t213']['payout_return'])} | Net: {fmt(t213_net)}")
        st.write("Wins: SF={sf} • Trips={tk} • Straight={st_} • Flush={fl}".format(
            sf=ss['t213']['wins']['straight_flush'], tk=ss['t213']['wins']['three_kind'],
            st_=ss['t213']['wins']['straight'], fl=ss['t213']['wins']['flush']
        ))

    cash_in = st.session_state.cash_in
    net = st.session_state.bankroll - cash_in
    roi = (net / cash_in * 100.0) if cash_in > 0 else 0.0
    with st.expander("💰 Profit & ROI"):
        st.write(f"Cash-in: {fmt(cash_in)}")
        st.write(f"Current bankroll: {fmt(st.session_state.bankroll)}")
        st.write(f"Net profit: {fmt(net)}")
        st.write(f"ROI: {roi:.2f}%")
