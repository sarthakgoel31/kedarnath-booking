# Kedarnath Helicopter Booking Flow (2026)

Source: YouTube walkthrough + portal testing on April 10, 2026

## Pre-requisites
- Chardham Yatra Registration done (Group ID: 6030093768, 7 members)
- IRCTC HeliYatra account (login: 9810695895 / Goels@657)
- Bookings open: April 11, 2026 at 12:00 noon
- Journey dates: April 22 - June 15, 2026

## The Flow

### Step 1: Login
- URL: https://www.heliyatra.irctc.co.in/auth
- Fill: Mobile Number (9810695895) + Password (Goels@657)
- Click: LOGIN button
- Result: Redirects to /app/trip/search (no CAPTCHA, no OTP confirmed in testing)

### Step 2: Click "BOOK TICKET" under Shri Kedarnath Dham
- On the main dashboard, click the Kedarnath "BOOK TICKET" button
- (NOT the Hemkund Sahib one)

### Step 3: Enter Group ID
- Field appears asking for Registration Number or Group ID
- Fill: **6030093768** (Group ID — since we have 7 people)
- This loads all 7 registered members

### Step 4: Select Date
- Calendar opens
- Select: **May 18, 2026** (registered Kedarnath date)
- Fallback: ±2 days (May 16, 17, 19, 20) if May 18 sold out

### Step 5: Operator + Helipad + Slot Selection
- Chart shows all helipads with operators and available slots
- Click on **Phata** helipad section
- This expands to show: United Helicharters, Thumby Aviation, Rajas Aerosports, Pilgrimage Aviation
- Each operator shows available slot counts
- Slot types:
  - **Same Day Return**: 6-9, 9-12, 12-3, 3-6 (1-1.5 hrs darshan)
  - **Next Day Return**: separate slots
- Prefer: **United Helicharters** (best safety) → any Phata operator with availability
- Prefer: **6-9 slot** (earliest, best weather, less crowd)

### Step 6: Click "Book Now"
- Shows ticket summary: operator name, slot timing, date
- Verify details are correct

### Step 7: Select Passengers (BOOKING 1 — max 6)
- All 7 group members shown as checkboxes
- **Tick 4 for booking 1**: Rakesh, Meenu, Nitin, Nidhi
- Fare displays on side (with GST + convenience fees)
- We do NOT fill forms — passengers are pre-loaded from Group ID registration

### Step 8: Click "Book Sheet"
- IMPORTANT: Button says "Book Sheet" not "Submit" or "Book Now"

### Step 9: OTP Verification
- OTP sent to profile email (nitinthegreat@gmail.com) AND mobile (9810695895)
- **Sarthak must get OTP from Nitin bhaiya's phone or email**
- Enter OTP → Click Submit

### Step 10: Pay and Confirm
- Tickets held for **15 minutes** — don't panic
- Click "Pay and Confirm"
- Payment: UPI or Net Banking
- **Sarthak pays manually**

### Step 11: BOOKING 2 (3 passengers)
- Go back to booking page
- Repeat Steps 3-10
- Tick 3 passengers: Sarthak, Smriti, Raghav
- Same operator/slot if available, otherwise next available

## Critical Notes
- Max 6 passengers per booking (we're doing 4+3)
- Max 12 tickets total from one login (6+6 slots)
- OTP goes to NITIN's phone/email (he's the account holder)
- 15-minute payment window after "Book Sheet"
- Same Day Return = 1-1.5 hrs at Kedarnath for darshan
- If May 18 sold out, try May 16/17/19/20 (±2 days from registered date)

## Bot Commands (for Claude driving kedarnath_bot.py)
1. `hammer` — hit portal until loaded
2. `navigate` → `/auth` — go to login
3. `fill_login` — fill mobile + password
4. `click` LOGIN — log in
5. `click` BOOK TICKET (Kedarnath) — enter booking flow
6. `fill` Group ID field → 6030093768
7. `click` date May 18 on calendar
8. `click` Phata → United Helicharters (or best available) → 6-9 slot
9. `click` Book Now
10. Tick 4 passengers (Rakesh, Meenu, Nitin, Nidhi)
11. `click` Book Sheet
12. **ASK SARTHAK**: "Enter OTP from Nitin's phone/email, then tell me"
13. `click` Pay and Confirm
14. **ASK SARTHAK**: "Pay now (UPI/Net Banking)"
15. Repeat 5-14 for booking 2 (Sarthak, Smriti, Raghav)
