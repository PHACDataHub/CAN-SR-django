from django_routify import Router

router = Router("/", "", auto_trailing_slash=True)
route = router.route
