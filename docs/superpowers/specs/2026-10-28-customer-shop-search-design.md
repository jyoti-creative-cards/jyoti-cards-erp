# Customer shop search

The signed-in Browse shop screen on the customer portal. A customer types an item, then a quantity, and sees whether that quantity is in stock. The search box is large, and it stays on screen while the product is in view.

## Goal

The search is the obvious control on Browse shop. Quantity is asked only after an item is set, and it starts empty. A valid lot shows the product. “Find products” does not sit on top of the product once the customer scrolls.

Sign-in, the bag, orders, stock wording, alternatives, and the server search stay as they are.

## What the customer sees

Phone first. The same layout on a wide screen, inside the current page width.

At the top, the hello card and the three tabs stay as they are. They sit in normal flow and scroll away.

Under them, one line: **Find products.** One sentence under it: “Type the item, then say how many.” There is no “Search catalogue” label and no dashed “Start with a search” box.

Under that sentence, one large box, full width, tall enough to tap easily. That box sticks to the top of the viewport. A short scroll moves the hello card, the tabs, the title, and the sentence off the screen. The box stays. The product shows directly under it.

The bag strip at the bottom stays when the bag has items.

The browse panel must not clip the box. The panel’s `overflow-hidden` would trap a sticky child, so the pin is to the viewport and the box is outside any clipping ancestor. The stock popup stays above the box.

## The two moments

One component, `customer-app/app/shop-finder.tsx`, owns the box. The page owns the search request, the cards, the cart, the hello card, and the tabs.

The finder has two moments.

### Search

The cursor is in the box. The placeholder is “Item number.” Typing keeps the cursor there. The suggestion list stays open under the box and shows our item numbers. The existing suggestions call runs after one character, 220 milliseconds after the last keystroke. A failed suggestion list is empty, and typing continues.

Enter, or the phone’s Done key, sets the item to the text after the existing shop-query normalization: trim, turn non-breaking spaces into spaces, and collapse repeated spaces. A tap on a list row sets the item to that row’s item number. An empty box does nothing. Enter does not pick a row the customer did not tap.

### Quantity

The same box becomes a large empty quantity field and the cursor moves into it. The number keyboard opens. The placeholder is “How many?” The item number sits above the box with the word Change. The field starts blank. There is no 50 filled in, and there is no Search button. While the field is empty or holds a valid lot, a line under it says “Lots of 50.”

A valid lot is a whole number from 50 through 100,000,000 that divides by 50. That is the same rule the order already uses.

The finder waits 400 milliseconds after the last keystroke. If the number is then a valid lot, the page loads the items. Typing 500 therefore does not load a result for 50. Enter or Done on a valid lot loads immediately and does not wait out the 400 milliseconds.

The page calls the existing `GET shop/products/search` with that item text and that quantity. It does not call search before both are set. The server’s default quantity is unchanged and unused by this screen.

Each card’s stock line is for the quantity in the box. Add to bag uses that same number, including on an alternative. Cards do not have their own quantity control. The bag still has its quantity control.

Changing the number to a new valid lot replaces the cards with the loading skeletons until the new result arrives. A newer request wins. An older response does not paint cards. Change, or an invalid number, cancels the in-flight request in the same way.

After a successful load, the number keyboard closes. Tapping the quantity box opens it again.

**Change** puts the cursor back in the search box, keeps the item text, and clears the quantity and the cards.

Returning to Browse shop restores the moment. If cards are already showing, the keyboard stays closed. If the finder is still on search, the cursor is in the search box.

## Failures

An empty quantity stays in the box, shows “Lots of 50.”, and shows no cards. A quantity that is not a valid lot stays in the box and the line changes to “Use a lot of 50.” No cards show. If cards were on screen, they hide, so the screen never shows stock for a different quantity.

A card still says in stock, low, or out for that quantity. Alternatives still appear when that quantity is short. Add to bag still refuses a quantity above what we have, with the same stock message as today.

No match is one line: “No matches. Try another item number.” Change is there.

If the load fails, the quantity stays and the cards stay hidden. One line says “Could not load. Try again.” Tapping that line, or Enter or Done, loads again.

## What stays

Sign-in, the bag, orders, the lot-of-50 rule, stock wording, alternatives, the godown message, and the server search stay as they are. The bag keeps its quantity dropdown. Only the browse cards lose theirs.

## Checks

`customer-app` has no UI test suite. This change does not alter the server search. Run the existing shop search tests and confirm they still pass.

Walk Browse shop in the browser, at a phone width and a wide width:

- One large search box. No quantity, no Search button, and no 50 filled in. The cursor is in the box. “Find products” is the title plus the one sentence above.
- Typing keeps the cursor in the box and opens the list. Quantity does not appear until Enter, Done, or a list tap.
- That sets the item, moves the cursor into an empty quantity box, and opens the number keyboard.
- 10 shows “Use a lot of 50” and no cards. 50 loads the cards after the pause, then the keyboard closes.
- 500 does not settle on a result for 50.
- A short scroll hides the hello card, the tabs, the title, and the sentence. The box stays pinned, with the product directly under it.
- Change returns to the search text, clears the quantity and the cards, and puts the cursor back in the search box.
- A short quantity still shows alternatives and blocks Add to bag. The bag and orders screens behave as they do today.
- A failed load keeps the quantity and offers try again.
