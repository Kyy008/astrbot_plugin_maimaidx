"""查分数据源路由。

根据用户设置的数据源（水鱼 / 落雪）分发查询请求。
内部统一为 PlayedResult / Best50 / Player，对外仍可转水鱼模型以复用绘图。
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple, Union

from .maimaidx_api_data import maiApi
from .maimaidx_error import TokenNotFoundError
from .maimaidx_lxns import (
    LxnsAPI,
    LxnsFeatureUnavailable,
    lxns_best50_to_best50,
    lxns_score_to_playinfodefault,
    lxns_scores_to_played,
    lxns_scores_to_records,
)
from .maimaidx_model import PlayInfoDefault, PlayInfoDev, UserInfo
from .maimaidx_play_result import (
    Best50,
    PlayedResult,
    Player,
    best50_to_userinfo,
    dx_star_from_scores,
    playinfo_to_played,
    played_list_to_plate,
    played_list_to_records,
    userinfo_to_best50,
    userinfo_to_player,
)
from .maimaidx_music import mai
from .maimaidx_user import ServiceName, User, userstore


def get_service(
    qqid: Optional[Union[int, str]], username: Optional[str] = None
) -> ServiceName:
    """解析应使用的数据源。查分器用户名（username）仅水鱼支持。"""
    if username:
        return ServiceName.DIVINGFISH
    if qqid is None:
        return ServiceName.DIVINGFISH
    return userstore.get(qqid).service


def is_lxns(qqid: Optional[Union[int, str]], username: Optional[str] = None) -> bool:
    return get_service(qqid, username) == ServiceName.LXNS


async def _friend_code(user: User) -> int:
    """获取用户好友码（优先缓存，否则按 QQ 查询并缓存）"""
    if user.friend_code:
        return user.friend_code
    try:
        numeric_qq = int(user.qqid)
    except (TypeError, ValueError) as exc:
        raise LxnsFeatureUnavailable(
            '当前平台用户标识不是 QQ 号，请先使用「绑定落雪」完成 OAuth 授权'
        ) from exc
    api = LxnsAPI(qqid=numeric_qq)
    player = await api.player_by_qq(numeric_qq)
    if player.friend_code:
        await userstore.update(user.qqid, friend_code=player.friend_code)
    return player.friend_code


# ---------------------------------------------------------------------------
# 统一 API（PlayedResult）
# ---------------------------------------------------------------------------
async def get_best50(
    qqid: Optional[Union[int, str]] = None,
    username: Optional[str] = None,
    *,
    all_perfect: bool = False,
    min_dx_star: Optional[int] = None,
    fitted: bool = False,
    all_perfect_plus: bool = False,
    achievement_mode: Optional[str] = None,
    difficulty_index: Optional[int] = None,
    all_songs: bool = False,
    ideal: bool = False,
    genre: Optional[str] = None,
    version: Optional[str] = None,
) -> Tuple[Player, Best50]:
    """按用户数据源获取普通、筛选、理想、分类、版本或不分版本的全曲 B50。"""
    if sum(
        (
            all_perfect,
            min_dx_star is not None,
            fitted,
            all_perfect_plus,
            achievement_mode is not None,
            difficulty_index is not None,
            all_songs,
            ideal,
            genre is not None,
            version is not None,
        )
    ) > 1:
        raise ValueError(
            'AP50、AP+50、DX 星级、拟合、理想、达成率、谱面难度、分类、版本'
            '与全曲 B50 不能同时启用'
        )
    if min_dx_star is not None and not 1 <= min_dx_star <= 5:
        raise ValueError('DX 星级必须在 1 到 5 之间')
    if difficulty_index is not None and not 0 <= difficulty_index <= 4:
        raise ValueError('谱面难度索引必须在 0 到 4 之间')
    versions = resolve_b50_versions(version) if version is not None else None

    if all_songs:
        if is_lxns(qqid, username):
            player, _ = await _lxns_best50_raw(qqid, all_perfect=False)
            records = await _lxns_records_raw(qqid, exact=False)
        else:
            player, records = await _divingfish_dev_records_raw(
                qqid=qqid, username=username
            )
        best50 = select_all_songs_b50_records(records)
    elif difficulty_index is not None:
        if is_lxns(qqid, username):
            player, _ = await _lxns_best50_raw(qqid, all_perfect=False)
            records = await _lxns_records_raw(qqid, exact=False)
        else:
            player, records = await _divingfish_dev_records_raw(
                qqid=qqid, username=username
            )
        best50 = select_difficulty_b50_records(
            records,
            difficulty_index,
            _is_new_song,
        )
    elif achievement_mode is not None:
        if is_lxns(qqid, username):
            player, _ = await _lxns_best50_raw(qqid, all_perfect=False)
            records = await _lxns_records_raw(qqid, exact=True)
        else:
            player, records = await _divingfish_dev_records_raw(
                qqid=qqid, username=username
            )
        best50 = select_achievement_b50_records(
            records,
            achievement_mode,
            _is_new_song,
        )
    elif all_perfect_plus:
        if is_lxns(qqid, username):
            player, _ = await _lxns_best50_raw(qqid, all_perfect=False)
            records = await _lxns_records_raw(qqid, exact=False)
        else:
            player, records = await _divingfish_dev_records_raw(
                qqid=qqid, username=username
            )
        best50 = select_ap_plus50_records(records, _is_new_song)
    elif fitted:
        if is_lxns(qqid, username):
            player, _ = await _lxns_best50_raw(qqid, all_perfect=False)
            records = await _lxns_records_raw(qqid, exact=False)
        else:
            player, records = await _divingfish_dev_records_raw(
                qqid=qqid, username=username
            )
        best50 = select_fitted_b50_records(
            records,
            _is_new_song,
            _fitted_level_value,
            _rating_for_level_value,
        )
    elif genre is not None:
        if is_lxns(qqid, username):
            player, _ = await _lxns_best50_raw(qqid, all_perfect=False)
            records = await _lxns_records_raw(qqid, exact=False)
        else:
            player, records = await _divingfish_dev_records_raw(
                qqid=qqid, username=username
            )
        best50 = select_genre_b50_records(
            records,
            genre,
            _is_new_song,
            _genre_for_song,
        )
    elif versions is not None:
        if is_lxns(qqid, username):
            player, _ = await _lxns_best50_raw(qqid, all_perfect=False)
            records = await _lxns_records_raw(qqid, exact=False)
        else:
            player, records = await _divingfish_dev_records_raw(
                qqid=qqid, username=username
            )
        best50 = select_version_b50_records(
            records,
            versions,
            _version_for_song,
        )
    elif ideal:
        if is_lxns(qqid, username):
            player, _ = await _lxns_best50_raw(qqid, all_perfect=False)
            records = await _lxns_records_raw(qqid, exact=False)
        else:
            player, records = await _divingfish_dev_records_raw(
                qqid=qqid, username=username
            )
        best50 = select_ideal_b50_records(
            records,
            _is_new_song,
            _rating_for_level_value,
        )
    elif min_dx_star is not None:
        if is_lxns(qqid, username):
            player, _ = await _lxns_best50_raw(qqid, all_perfect=False)
            records = await _lxns_records_raw(qqid, exact=False)
        else:
            player, records = await _divingfish_dev_records_raw(
                qqid=qqid, username=username
            )
        best50 = select_star_b50_records(
            records,
            min_dx_star,
            _is_new_song,
            _dx_star_for_record,
        )
    elif is_lxns(qqid, username):
        player, best50 = await _lxns_best50_raw(
            qqid, all_perfect=all_perfect
        )
    elif all_perfect:
        player, best50 = await _divingfish_ap50_raw(
            qqid=qqid, username=username
        )
    else:
        user = await maiApi.query_user_b50(qqid=qqid, username=username)
        return userinfo_to_player(user), userinfo_to_best50(user)

    if (
        all_perfect
        or all_perfect_plus
        or min_dx_star is not None
        or fitted
        or ideal
        or genre is not None
        or version is not None
        or achievement_mode is not None
        or difficulty_index is not None
        or all_songs
    ):
        filtered_rating = best50.sd_total + best50.dx_total
        player = player.model_copy(update={'rating': filtered_rating})
    return player, best50


def select_all_songs_b50_records(records: List[PlayedResult]) -> Best50:
    """忽略新旧曲分类，按单曲 Rating 选出最高的 50 个成绩。"""
    sort_key = lambda r: (
        r.rating,
        r.achievements,
        r.level_value,
        r.song_id,
        r.level_index,
    )
    top50 = sorted(records, key=sort_key, reverse=True)[:50]

    # Best50 数据结构仍以 35 + 15 保存，以兼容既有模型转换；
    # 全曲模式渲染时会将两段重新合并并连续绘制。
    first35 = top50[:35]
    last15 = top50[35:]
    return Best50(
        sd_total=sum(record.rating for record in first35),
        dx_total=sum(record.rating for record in last15),
        sd=first35,
        dx=last15,
    )


def resolve_b50_versions(token: str) -> List[str]:
    """将版本字（可连续多个）解析为曲库版本名列表，多个版本取并集。"""
    from .. import B50_VERSION_CHARS, platecn, version_map

    versions: List[str] = []
    for char in token:
        if char not in B50_VERSION_CHARS:
            raise ValueError(f'未知的版本：{char}')
        for name in version_map[platecn.get(char, char)][0]:
            if name not in versions:
                versions.append(name)
    if not versions:
        raise ValueError('版本不能为空')
    return versions


def select_genre_b50_records(
    records: List[PlayedResult],
    genre: str,
    is_new_song: Callable[[int], Optional[bool]],
    genre_of: Callable[[int], Optional[str]],
) -> Best50:
    """按曲目分类筛选完整成绩，再选出旧曲 35 与新曲 15。"""
    old_records: List[PlayedResult] = []
    new_records: List[PlayedResult] = []
    for record in records:
        if record.song_id >= 100000 or genre_of(record.song_id) != genre:
            continue
        is_new = is_new_song(record.song_id)
        if is_new is None:
            continue
        (new_records if is_new else old_records).append(record)

    sort_key = lambda r: (
        r.rating,
        r.achievements,
        r.level_value,
        r.song_id,
        r.level_index,
    )
    b35 = sorted(old_records, key=sort_key, reverse=True)[:35]
    b15 = sorted(new_records, key=sort_key, reverse=True)[:15]
    return Best50(
        sd_total=sum(record.rating for record in b35),
        dx_total=sum(record.rating for record in b15),
        sd=b35,
        dx=b15,
    )


def select_version_b50_records(
    records: List[PlayedResult],
    versions: List[str],
    version_of: Callable[[int], Optional[str]],
) -> Best50:
    """按曲目版本筛选完整成绩，不分新旧曲选出 Rating 最高的 50 个。"""
    allowed = set(versions)
    return select_all_songs_b50_records(
        [
            record
            for record in records
            if record.song_id < 100000 and version_of(record.song_id) in allowed
        ]
    )


def select_ap50_records(
    records: List[PlayedResult],
    is_new_song: Callable[[int], Optional[bool]],
) -> Best50:
    """从完整成绩中选出旧曲 AP35 与新曲 AP15。"""
    old_records: List[PlayedResult] = []
    new_records: List[PlayedResult] = []

    for record in records:
        if (record.fc or '').lower() not in {'ap', 'app'}:
            continue
        is_new = is_new_song(record.song_id)
        if is_new is None:
            continue
        (new_records if is_new else old_records).append(record)

    sort_key = lambda r: (
        r.rating,
        r.achievements,
        r.level_value,
        r.song_id,
        r.level_index,
    )
    ap35 = sorted(old_records, key=sort_key, reverse=True)[:35]
    ap15 = sorted(new_records, key=sort_key, reverse=True)[:15]
    return Best50(
        sd_total=sum(record.rating for record in ap35),
        dx_total=sum(record.rating for record in ap15),
        sd=ap35,
        dx=ap15,
    )


def select_ap_plus50_records(
    records: List[PlayedResult],
    is_new_song: Callable[[int], Optional[bool]],
) -> Best50:
    """从玩家完整成绩中选出旧曲 AP+35 与新曲 AP+15。"""
    old_records: List[PlayedResult] = []
    new_records: List[PlayedResult] = []
    for record in records:
        if (record.fc or '').lower() != 'app':
            continue
        is_new = is_new_song(record.song_id)
        if is_new is None:
            continue
        (new_records if is_new else old_records).append(record)

    sort_key = lambda r: (
        r.rating,
        r.achievements,
        r.level_value,
        r.song_id,
        r.level_index,
    )
    app35 = sorted(old_records, key=sort_key, reverse=True)[:35]
    app15 = sorted(new_records, key=sort_key, reverse=True)[:15]
    return Best50(
        sd_total=sum(record.rating for record in app35),
        dx_total=sum(record.rating for record in app15),
        sd=app35,
        dx=app15,
    )


ACHIEVEMENT_B50_MODES = frozenset({'under_s', 'near', 'lock'})


def achievement_matches_mode(achievements: float, mode: str) -> bool:
    """判断达成率是否属于指定的特殊 B50 区间。"""
    if mode not in ACHIEVEMENT_B50_MODES:
        raise ValueError(f'未知的达成率筛选模式：{mode}')

    value = float(achievements)
    if mode == 'under_s':
        return value < 97.0
    if mode == 'near':
        return (
            99.95 <= value <= 99.9999
            or 100.45 <= value <= 100.4999
        )
    return (
        100.0 <= value <= 100.05
        or 100.5 <= value <= 100.55
    )


def select_achievement_b50_records(
    records: List[PlayedResult],
    mode: str,
    is_new_song: Callable[[int], Optional[bool]],
) -> Best50:
    """按达成率区间筛选完整成绩，再选出旧曲 35 与新曲 15。"""
    if mode not in ACHIEVEMENT_B50_MODES:
        raise ValueError(f'未知的达成率筛选模式：{mode}')

    old_records: List[PlayedResult] = []
    new_records: List[PlayedResult] = []
    for record in records:
        if not achievement_matches_mode(record.achievements, mode):
            continue
        is_new = is_new_song(record.song_id)
        if is_new is None:
            continue
        (new_records if is_new else old_records).append(record)

    sort_key = lambda r: (
        r.rating,
        r.achievements,
        r.level_value,
        r.song_id,
        r.level_index,
    )
    b35 = sorted(old_records, key=sort_key, reverse=True)[:35]
    b15 = sorted(new_records, key=sort_key, reverse=True)[:15]
    return Best50(
        sd_total=sum(record.rating for record in b35),
        dx_total=sum(record.rating for record in b15),
        sd=b35,
        dx=b15,
    )


def select_difficulty_b50_records(
    records: List[PlayedResult],
    difficulty_index: int,
    is_new_song: Callable[[int], Optional[bool]],
) -> Best50:
    """按谱面难度筛选完整成绩，再选出旧曲 35 与新曲 15。"""
    if not 0 <= difficulty_index <= 4:
        raise ValueError('谱面难度索引必须在 0 到 4 之间')

    old_records: List[PlayedResult] = []
    new_records: List[PlayedResult] = []
    for record in records:
        if record.level_index != difficulty_index:
            continue
        is_new = is_new_song(record.song_id)
        if is_new is None:
            continue
        (new_records if is_new else old_records).append(record)

    sort_key = lambda r: (
        r.rating,
        r.achievements,
        r.level_value,
        r.song_id,
        r.level_index,
    )
    b35 = sorted(old_records, key=sort_key, reverse=True)[:35]
    b15 = sorted(new_records, key=sort_key, reverse=True)[:15]
    return Best50(
        sd_total=sum(record.rating for record in b35),
        dx_total=sum(record.rating for record in b15),
        sd=b35,
        dx=b15,
    )


def select_star_b50_records(
    records: List[PlayedResult],
    min_dx_star: int,
    is_new_song: Callable[[int], Optional[bool]],
    dx_star_of: Callable[[PlayedResult], Optional[int]],
) -> Best50:
    """从完整成绩中选出 DX SCORE 至少 N 星的 B35 与 B15。"""
    if not 1 <= min_dx_star <= 5:
        raise ValueError('DX 星级必须在 1 到 5 之间')

    old_records: List[PlayedResult] = []
    new_records: List[PlayedResult] = []
    for record in records:
        dx_star = dx_star_of(record)
        if dx_star is None or dx_star < min_dx_star:
            continue
        is_new = is_new_song(record.song_id)
        if is_new is None:
            continue
        (new_records if is_new else old_records).append(record)

    sort_key = lambda r: (
        r.rating,
        r.achievements,
        r.level_value,
        r.song_id,
        r.level_index,
    )
    b35 = sorted(old_records, key=sort_key, reverse=True)[:35]
    b15 = sorted(new_records, key=sort_key, reverse=True)[:15]
    return Best50(
        sd_total=sum(record.rating for record in b35),
        dx_total=sum(record.rating for record in b15),
        sd=b35,
        dx=b15,
    )


def select_fitted_b50_records(
    records: List[PlayedResult],
    is_new_song: Callable[[int], Optional[bool]],
    fitted_level_value_of: Callable[[PlayedResult], Optional[float]],
    rating_of: Callable[[float, float], int],
) -> Best50:
    """用拟合定数重算 Rating，并选出拟合 B35 与 B15。"""
    old_records: List[PlayedResult] = []
    new_records: List[PlayedResult] = []
    for record in records:
        if record.song_id >= 100000:
            continue
        fitted_level_value = fitted_level_value_of(record)
        if fitted_level_value is None or fitted_level_value <= 0:
            continue
        is_new = is_new_song(record.song_id)
        if is_new is None:
            continue
        fitted_record = record.model_copy(
            update={
                'level_value': fitted_level_value,
                'rating': rating_of(fitted_level_value, record.achievements),
            }
        )
        (new_records if is_new else old_records).append(fitted_record)

    sort_key = lambda r: (
        r.rating,
        r.achievements,
        r.level_value,
        r.song_id,
        r.level_index,
    )
    b35 = sorted(old_records, key=sort_key, reverse=True)[:35]
    b15 = sorted(new_records, key=sort_key, reverse=True)[:15]
    return Best50(
        sd_total=sum(record.rating for record in b35),
        dx_total=sum(record.rating for record in b15),
        sd=b35,
        dx=b15,
    )


IDEAL_ACHIEVEMENT_THRESHOLDS = (
    50.0,
    60.0,
    70.0,
    75.0,
    80.0,
    90.0,
    94.0,
    97.0,
    98.0,
    99.0,
    99.5,
    100.0,
    100.5,
    101.0,
)


def _next_ideal_achievement(achievements: float) -> float:
    """返回当前评价提升一档后的代表达成率。"""
    for threshold in IDEAL_ACHIEVEMENT_THRESHOLDS:
        if achievements < threshold:
            return threshold
    return 101.0


def select_ideal_b50_records(
    records: List[PlayedResult],
    is_new_song: Callable[[int], Optional[bool]],
    rating_of: Callable[[float, float], int],
) -> Best50:
    """将每个已有成绩提升一个评价档位后，重新选出理想 B35 与 B15。"""
    from .maimai_best_50 import computeRa

    old_records: List[PlayedResult] = []
    new_records: List[PlayedResult] = []
    for record in records:
        if record.song_id >= 100000 or record.level_value <= 0:
            continue
        is_new = is_new_song(record.song_id)
        if is_new is None:
            continue

        ideal_achievement = _next_ideal_achievement(record.achievements)
        ideal_rate = computeRa(
            record.level_value, ideal_achievement, onlyrate=True
        )
        update = {
            'achievements': ideal_achievement,
            'rating': rating_of(record.level_value, ideal_achievement),
            'rate': ideal_rate.lower(),
        }
        if ideal_achievement >= 101.0:
            update['fc'] = 'app'
        ideal_record = record.model_copy(update=update)
        (new_records if is_new else old_records).append(ideal_record)

    sort_key = lambda r: (
        r.rating,
        r.achievements,
        r.level_value,
        r.song_id,
        r.level_index,
    )
    b35 = sorted(old_records, key=sort_key, reverse=True)[:35]
    b15 = sorted(new_records, key=sort_key, reverse=True)[:15]
    return Best50(
        sd_total=sum(record.rating for record in b35),
        dx_total=sum(record.rating for record in b15),
        sd=b35,
        dx=b15,
    )


def _is_new_song(song_id: int) -> Optional[bool]:
    song = mai.get_song(song_id)
    return song.isnew if song else None


def _genre_for_song(song_id: int) -> Optional[str]:
    song = mai.get_song(song_id)
    return song.genre if song else None


def _version_for_song(song_id: int) -> Optional[str]:
    song = mai.get_song(song_id)
    return song.version_str if song else None


def _dx_star_for_record(record: PlayedResult) -> Optional[int]:
    """取得成绩的 DX SCORE 星级；水鱼成绩按谱面物量计算。"""
    if record.dx_star is not None and (
        record.dx_star > 0 or record.dx_score <= 0
    ):
        return record.dx_star
    difficulty = mai.get_difficulty(record.song_id, record.level_index)
    if difficulty is None:
        return None
    return dx_star_from_scores(record.dx_score, difficulty.dx_score)


def _fitted_level_value(record: PlayedResult) -> Optional[float]:
    """读取谱面拟合定数；暂无统计时回退到官方定数。"""
    difficulty = mai.get_difficulty(record.song_id, record.level_index)
    stats = difficulty.stats if difficulty else None
    if stats and stats.fit_diff is not None:
        return round(stats.fit_diff, 2)
    return record.level_value or None


def _rating_for_level_value(level_value: float, achievements: float) -> int:
    """按指定定数和达成率计算单曲 Rating。"""
    from .maimai_best_50 import computeRa

    return int(computeRa(level_value, achievements))


async def _divingfish_dev_records_raw(
    qqid: Optional[Union[int, str]] = None,
    username: Optional[str] = None,
) -> Tuple[Player, List[PlayedResult]]:
    """通过水鱼 OAuth 或旧开发者接口读取完整成绩。"""
    if not maiApi.divingfish_oauth_configured and not maiApi.token:
        raise TokenNotFoundError
    user = await maiApi.query_user_get_dev(qqid=qqid, username=username)
    records = [playinfo_to_played(record) for record in (user.records or [])]
    return userinfo_to_player(user), records


async def _divingfish_ap50_raw(
    qqid: Optional[Union[int, str]] = None,
    username: Optional[str] = None,
) -> Tuple[Player, Best50]:
    """使用水鱼开发者接口的完整成绩生成 AP50。"""
    player, records = await _divingfish_dev_records_raw(
        qqid=qqid, username=username
    )
    return player, select_ap50_records(records, _is_new_song)


async def get_records(
    qqid: Optional[Union[int, str]] = None,
    username: Optional[str] = None,
    *,
    exact: bool = False,
) -> List[PlayedResult]:
    """获取全部成绩（统一 PlayedResult）。

    水鱼优先 OAuth/开发者全量 records；未配置时回退旧 plate（全版本）。
    """
    from .. import plate_to_dx_version
    if is_lxns(qqid, username):
        return await _lxns_records_raw(qqid, exact=exact)

    if maiApi.divingfish_oauth_configured or maiApi.token:
        dev = await maiApi.query_user_get_dev(qqid=qqid, username=username)
        return [playinfo_to_played(r) for r in (dev.records or [])]

    from .maimai_best_50 import computeRa
    from .maimaidx_play_result import lookup_meta

    plate = await maiApi.query_user_plate(
        qqid=qqid,
        username=username,
        version=list(plate_to_dx_version.values()),
    )
    result: List[PlayedResult] = []
    for r in plate:
        p = playinfo_to_played(r)
        if not p.level_value:
            ds, level, title = lookup_meta(p.song_id, p.level_index)
            ra, rate = (
                computeRa(ds, p.achievements, israte=True) if ds else (p.rating, p.rate or 'd')
            )
            p = p.model_copy(
                update={
                    'level_value': ds,
                    'level': level or p.level,
                    'song_name': title or p.song_name,
                    'rating': int(ra) if ds else p.rating,
                    'rate': (rate.lower() if isinstance(rate, str) else p.rate),
                }
            )
        result.append(p)
    return result


async def get_player_b50_userinfo(
    qqid: Optional[Union[int, str]] = None,
    username: Optional[str] = None,
    *,
    all_perfect: bool = False,
    min_dx_star: Optional[int] = None,
    fitted: bool = False,
    all_perfect_plus: bool = False,
    achievement_mode: Optional[str] = None,
    difficulty_index: Optional[int] = None,
    all_songs: bool = False,
    ideal: bool = False,
    genre: Optional[str] = None,
    version: Optional[str] = None,
) -> UserInfo:
    """统一取 b50 并转为 UserInfo，供现有绘图直接使用。"""
    player, best50 = await get_best50(
        qqid,
        username,
        all_perfect=all_perfect,
        min_dx_star=min_dx_star,
        fitted=fitted,
        all_perfect_plus=all_perfect_plus,
        achievement_mode=achievement_mode,
        difficulty_index=difficulty_index,
        all_songs=all_songs,
        ideal=ideal,
        genre=genre,
        version=version,
    )
    return best50_to_userinfo(player, best50)


async def get_plate(
    qqid: Optional[Union[int, str]] = None,
    username: Optional[str] = None,
    *,
    version: Optional[List[str]] = None,
    exact: bool = False,
) -> List[PlayInfoDefault]:
    """统一取成绩列表（PlayInfoDefault），水鱼可按 version 过滤。"""
    if is_lxns(qqid, username):
        return await lxns_plate(qqid, exact=exact)
    if version is None:
        from .. import plate_to_dx_version

        version = list(plate_to_dx_version.values())
    return await maiApi.query_user_plate(qqid=qqid, username=username, version=version)


async def get_player_records(
    qqid: Optional[Union[int, str]] = None,
    username: Optional[str] = None,
    *,
    exact: bool = False,
) -> List[PlayInfoDev]:
    """统一取成绩列表（PlayInfoDev），供进度 / 分数列表使用。"""
    return played_list_to_records(
        await get_records(qqid=qqid, username=username, exact=exact)
    )


async def get_music_record(
    qqid: Union[int, str],
    music_id: Union[int, str],
    username: Optional[str] = None,
) -> List[PlayInfoDev]:
    """统一取单曲成绩。未配置 OAuth/token 时用旧 plate 回退。"""
    from .. import plate_to_dx_version
    from .maimaidx_play_result import playinfo_to_played

    if is_lxns(qqid, username):
        return await lxns_music_record(qqid, music_id)
    if maiApi.divingfish_oauth_configured or maiApi.token:
        return await maiApi.query_user_post_dev(
            qqid=qqid, username=username, music_id=music_id
        )
    version = list(set(plate_to_dx_version.values()))
    plate = await maiApi.query_user_plate(
        qqid=qqid, username=username, version=version
    )
    mid = int(music_id)
    played = [
        playinfo_to_played(r) for r in plate if int(getattr(r, 'song_id', 0)) == mid
    ]
    return played_list_to_records(played)


# ---------------------------------------------------------------------------
# 落雪取数（兼容旧导出：仍返回水鱼模型）
# ---------------------------------------------------------------------------
async def _lxns_best50_raw(
    qqid: Union[int, str], *, all_perfect: bool = False
) -> Tuple[Player, Best50]:
    user = userstore.get(qqid)
    api = LxnsAPI(
        qqid=user.qqid,
        access_token=user.access_token,
        refresh_token=user.refresh_token,
    )
    if user.access_token:
        player = await api.player_personal()
        if not all_perfect:
            best50 = await api.bests_personal()
        else:
            if not maiApi.config.lxns_dev_token:
                raise LxnsFeatureUnavailable(
                    'ap50 需要 BOT 管理员配置落雪开发者 Token'
                )
            best50 = await api.bests_by_friend_code(
                await _friend_code(user), ap=True
            )
    else:
        if not maiApi.config.lxns_dev_token:
            raise LxnsFeatureUnavailable(
                'ap50 / 开发者查询需要 BOT 管理员配置落雪开发者 Token'
                if all_perfect
                else 'BOT 管理员未配置落雪开发者 Token，无法按 QQ 查询'
            )
        fc = await _friend_code(user)
        player = await api.player_by_qq(int(user.qqid))
        best50 = await api.bests_by_friend_code(fc, ap=all_perfect)
    return lxns_best50_to_best50(player, best50)


async def _lxns_records_raw(
    qqid: Union[int, str], *, exact: bool = False
) -> List[PlayedResult]:
    user = userstore.get(qqid)
    api = LxnsAPI(
        qqid=user.qqid,
        access_token=user.access_token,
        refresh_token=user.refresh_token,
    )
    if user.access_token:
        scores = await api.all_scores_personal()
        return lxns_scores_to_played(scores)
    if exact:
        raise LxnsFeatureUnavailable(
            '该功能需要精确达成率，落雪「开发者 Token」模式不支持；'
            '请使用「绑定落雪」进行 OAuth 授权，或用「数据源」切回水鱼。'
        )
    if not maiApi.config.lxns_dev_token:
        raise LxnsFeatureUnavailable('BOT 管理员未配置落雪开发者 Token')
    fc = await _friend_code(user)
    scores = await api.simple_scores_by_friend_code(fc)
    return lxns_scores_to_played(scores)


async def lxns_b50(qqid: Union[int, str], all_perfect: bool = False) -> UserInfo:
    player, best50 = await _lxns_best50_raw(qqid, all_perfect=all_perfect)
    return best50_to_userinfo(player, best50)


async def lxns_records(qqid: Union[int, str], *, exact: bool = False) -> List[PlayInfoDev]:
    return played_list_to_records(await _lxns_records_raw(qqid, exact=exact))


async def lxns_plate(qqid: Union[int, str], *, exact: bool = False) -> List[PlayInfoDefault]:
    return played_list_to_plate(await _lxns_records_raw(qqid, exact=exact))


async def lxns_music_record(qqid: Union[int, str], music_id: Union[int, str]) -> List[PlayInfoDev]:
    user = userstore.get(qqid)
    api = LxnsAPI(
        qqid=user.qqid,
        access_token=user.access_token,
        refresh_token=user.refresh_token,
    )
    df_id = int(music_id)
    if df_id >= 100000:
        song_type, lxns_id = 'utage', df_id
    elif df_id >= 10000:
        song_type, lxns_id = 'dx', df_id - 10000
    else:
        song_type, lxns_id = 'standard', df_id
    if user.access_token:
        scores = await api.song_bests_personal(lxns_id, song_type)
    else:
        if not maiApi.config.lxns_dev_token:
            raise LxnsFeatureUnavailable('BOT 管理员未配置落雪开发者 Token')
        fc = await _friend_code(user)
        scores = await api.song_bests_by_friend_code(fc, lxns_id, song_type)
    return lxns_scores_to_records(scores)


# 兼容旧符号
__all__ = [
    'get_service',
    'is_lxns',
    'get_best50',
    'select_ap50_records',
    'select_ap_plus50_records',
    'achievement_matches_mode',
    'select_achievement_b50_records',
    'select_difficulty_b50_records',
    'select_all_songs_b50_records',
    'select_star_b50_records',
    'select_fitted_b50_records',
    'select_ideal_b50_records',
    'resolve_b50_versions',
    'select_genre_b50_records',
    'select_version_b50_records',
    'get_records',
    'get_player_b50_userinfo',
    'get_plate',
    'get_player_records',
    'get_music_record',
    'lxns_b50',
    'lxns_records',
    'lxns_plate',
    'lxns_music_record',
    'lxns_score_to_playinfodefault',
]
