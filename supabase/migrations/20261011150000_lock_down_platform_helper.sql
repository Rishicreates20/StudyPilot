-- Lock down the one function Supabase itself adds to the `public` schema.
--
-- Hosted Supabase projects can have `public.rls_auto_enable()`: an event-trigger function (owned by
-- `postgres`, SECURITY DEFINER) that turns row security on for every new table. Supabase's default
-- privileges let `anon` and `authenticated` execute functions in `public`, so the security advisor
-- reports it as callable through the REST API (`/rest/v1/rpc/rls_auto_enable`).
--
-- It cannot do anything useful when called directly (it only runs as an event trigger, and only
-- enables row security), but nothing outside the platform should be able to call a SECURITY
-- DEFINER function, so execute is removed from every client role. Event triggers fire with the
-- privileges of whoever runs the DDL, not of the roles revoked here, so new tables still get
-- row security.
--
-- The function exists on hosted projects and not on a bare database or the local Supabase stack,
-- hence the check: this migration must succeed on all of them, and can be run twice.

do $$
begin
  if to_regprocedure('public.rls_auto_enable()') is not null then
    revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
  end if;
end;
$$;
