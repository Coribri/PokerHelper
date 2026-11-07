# engine.py
import random
from collections import Counter
from itertools import combinations

# 牌面定义: 2-9, T, J, Q, K, A; 花色: s, h, d, c
RANKS = "23456789TJQKA"
SUITS = "shdc"
DECK = [r + s for r in RANKS for s in SUITS]
RANK_DICT = {r: i for i, r in enumerate(RANKS, start=2)}
RANK_NAME = {
    14: "A",
    13: "K",
    12: "Q",
    11: "J",
    10: "T",
    9: "9",
    8: "8",
    7: "7",
    6: "6",
    5: "5",
    4: "4",
    3: "3",
    2: "2",
}


def evaluate_5card(cards):
    """
    对 5 张牌打分，返回值越大牌力越强
    类别: 8:同花顺, 7:四条, 6:葫芦, 5:同花, 4:顺子, 3:三条, 2:两对, 1:一对, 0:高牌
    """
    ranks = sorted([RANK_DICT[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]

    is_flush = len(set(suits)) == 1

    # 判断顺子 (考虑 A-2-3-4-5 特殊情况)
    is_straight = False
    straight_high = 0
    distinct_ranks = sorted(list(set(ranks)), reverse=True)
    if len(distinct_ranks) == 5:
        if distinct_ranks[0] - distinct_ranks[4] == 4:
            is_straight = True
            straight_high = distinct_ranks[0]
        elif distinct_ranks == [14, 5, 4, 3, 2]:
            is_straight = True
            straight_high = 5

    counts = Counter(ranks).most_common()

    if is_flush and is_straight:
        return (8, straight_high)
    if counts[0][1] == 4:
        return (7, counts[0][0], counts[1][0])
    if counts[0][1] == 3 and counts[1][1] == 2:
        return (6, counts[0][0], counts[1][0])
    if is_flush:
        return (5, ranks)
    if is_straight:
        return (4, straight_high)
    if counts[0][1] == 3:
        kickers = [k for k, _ in counts[1:]]
        return (3, counts[0][0], kickers)
    if counts[0][1] == 2 and counts[1][1] == 2:
        high_pair = max(counts[0][0], counts[1][0])
        low_pair = min(counts[0][0], counts[1][0])
        return (2, high_pair, low_pair, counts[2][0])
    if counts[0][1] == 2:
        kickers = [k for k, _ in counts[1:]]
        return (1, counts[0][0], kickers)
    return (0, ranks)


def evaluate_hand(cards):
    """从 5-7 张牌中挑出最强的 5 张牌的评分"""
    return max(evaluate_5card(comb) for comb in combinations(cards, 5))


def get_hand_type_desc(my_cards, board_cards):
    """返回当前手牌+公共牌结合组成的最大牌型中文描述"""
    all_cards = my_cards + board_cards
    if len(all_cards) < 5:
        if len(my_cards) == 2:
            r1, r2 = my_cards[0][0], my_cards[1][0]
            suited = "同花" if my_cards[0][1] == my_cards[1][1] else "杂色"
            if r1 == r2:
                return f"起手对子 ({r1}{r2})"
            return f"起手高牌 ({r1}{r2} {suited})"
        return "等待发牌"

    score = evaluate_hand(all_cards)
    category = score[0]

    if category == 8:
        return f"同花顺 ({RANK_NAME[score[1]]}高)"
    elif category == 7:
        return f"四条 (金刚 {RANK_NAME[score[1]]})"
    elif category == 6:
        return f"葫芦 ({RANK_NAME[score[1]]}带{RANK_NAME[score[2]]})"
    elif category == 5:
        return f"同花 ({RANK_NAME[score[1][0]]}高)"
    elif category == 4:
        return f"顺子 ({RANK_NAME[score[1]]}高)"
    elif category == 3:
        return f"三条 ({RANK_NAME[score[1]]})"
    elif category == 2:
        return f"两对 ({RANK_NAME[score[1]]}和{RANK_NAME[score[2]]})"
    elif category == 1:
        return f"一对 ({RANK_NAME[score[1]]})"
    else:
        return f"高牌 ({RANK_NAME[score[1][0]]})"


def calculate_equity(my_cards, board_cards, num_opponents=1, iterations=1200):
    """
    蒙特卡洛模拟胜率
    my_cards: ['As', 'Kd']
    board_cards: ['2c', '7h', 'Jd'] (翻牌/转牌/河牌，允许为空列表)
    """
    if not my_cards or len(my_cards) < 2:
        return 0.0, 0.0

    known_cards = set(my_cards + board_cards)
    available_deck = [c for c in DECK if c not in known_cards]

    wins = 0
    ties = 0

    for _ in range(iterations):
        deck = available_deck.copy()
        random.shuffle(deck)

        cards_needed = 5 - len(board_cards)
        current_board = board_cards + [deck.pop() for _ in range(cards_needed)]

        my_score = evaluate_hand(my_cards + current_board)

        is_tie = False
        lost = False

        for _ in range(num_opponents):
            opp_cards = [deck.pop(), deck.pop()]
            opp_score = evaluate_hand(opp_cards + current_board)

            if opp_score > my_score:
                lost = True
                break
            elif opp_score == my_score:
                is_tie = True

        if not lost:
            if is_tie:
                ties += 1
            else:
                wins += 1

    win_rate = (wins / iterations) * 100
    tie_rate = (ties / iterations) * 100
    return win_rate, tie_rate